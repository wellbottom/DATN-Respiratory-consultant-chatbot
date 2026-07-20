"""RAGAS-style + ROUGE evaluation metrics for the generated QA dataset.

This module implements the five metrics described in the thesis "Evaluation
Metrics" section, applied to a generated QA JSONL file such as
``data/qa_generation_artifacts/main/vinmec_child_articles.qa.jsonl``.

Metric -> formula mapping (kept faithful to the thesis text)
------------------------------------------------------------
RAGAS (LLM-as-judge, semantic):
    * Faithfulness        = |V| / |S|
        - S = statements extracted from the answer
        - V = statements that can be inferred from the context
    * Answer Relevancy    = (1/n) * sum_i cos(e_q, e_{q_i})
        - generate n questions from the answer, embed them, compare to the
          embedding of the original question
    * Context Precision@K = sum_k (Precision@k * v_k) / (#relevant chunks in Top-K)
        - v_k = 1 if the chunk at rank k is relevant to the answer/ground truth
    * Context Recall      = |GT_attributed| / |GT|
        - GT = statements in the ground-truth answer
        - GT_attributed = GT statements inferable from the retrieved context

ROUGE (lexical overlap of answer vs. ground truth):
    * ROUGE-1 / ROUGE-2 = matching n-gram count / reference n-gram count
    * ROUGE-L           = F_lcs from LCS-based precision/recall

Field mapping for this dataset (schema v2 rows)
-----------------------------------------------
    question      -> the user question (q)
    answer        -> the generated answer (the text being evaluated)
    context       -> the retrieved context the answer was grounded on
    evidence_span -> the supporting span inside the source section
    source_url    -> citation, used only for reporting

IMPORTANT honest caveats about THIS dataset
--------------------------------------------
1. The dataset is *synthetic*: the answer is generated FROM the same context.
   There is no independent human "ground truth" answer. We therefore treat the
   ``evidence_span`` (falling back to ``context``) as a proxy ground truth for
   Context Recall and ROUGE. This is a proxy, not a gold reference, so ROUGE /
   Context Recall here mostly measure how tightly the answer tracks its own
   evidence rather than agreement with an external gold answer.
2. Each row stores a single ``context`` string, not a ranked list of retrieved
   chunks. Context Precision@K needs ranked chunks, so by default we split the
   single context into paragraph-level "chunks" and rank them by similarity to
   the answer. With a single chunk this collapses to a hit/no-hit precision.
   If you have real retrieved chunks per question, pass them in via
   ``chunks_field`` (a row field containing a list of chunk strings).

The metric functions themselves are generic and reusable; the caveats only
affect how the orchestration layer (`evaluate_dataset`) feeds data into them.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from embedding_pipeline.common import (  # noqa: E402
    canonical_unicode,
    iter_jsonl,
    load_project_env,
    normalize_for_match,
    simple_word_tokenize,
)
from embedding_pipeline.embedding import BaseEmbedder, build_embedder  # noqa: E402


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?…])\s+|\n+")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.\)])\s+", re.MULTILINE)


def split_into_statements(text: str) -> list[str]:
    """Split an answer / ground truth into individual statements.

    Splits on sentence terminators, newlines and bullet markers, then keeps
    fragments that contain at least one word token. This backs the
    ``|S|`` / ``|GT|`` denominators in the Faithfulness and Context Recall
    formulas.
    """

    text = canonical_unicode(text or "").strip()
    if not text:
        return []

    # Normalise bullet markers into sentence boundaries so list items become
    # separate statements.
    text = _BULLET_RE.sub("\n", text)
    raw_parts = _SENTENCE_SPLIT_RE.split(text)

    statements: list[str] = []
    for part in raw_parts:
        candidate = part.strip(" \t\r\n-•*")
        if not candidate:
            continue
        if not simple_word_tokenize(candidate):
            continue
        statements.append(candidate)
    return statements


def _ngrams(tokens: Sequence[str], n: int) -> list[tuple[str, ...]]:
    if n <= 0 or len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    """Length of the longest common subsequence (token level)."""

    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    for token_a in a:
        current = [0]
        for j, token_b in enumerate(b, start=1):
            if token_a == token_b:
                current.append(previous[j - 1] + 1)
            else:
                current.append(max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _score_triplet(precision: float, recall: float, *, beta: float = 1.0) -> dict[str, float]:
    if precision <= 0.0 or recall <= 0.0:
        return {"precision": precision, "recall": recall, "f1": 0.0}
    beta_sq = beta * beta
    return {
        "precision": precision,
        "recall": recall,
        "f1": (1 + beta_sq) * precision * recall / (recall + beta_sq * precision),
    }


# ---------------------------------------------------------------------------
# ROUGE metrics (lexical, no model required)
# ---------------------------------------------------------------------------

def rouge_n(candidate: str, reference: str, *, n: int = 1) -> dict[str, float]:
    """ROUGE-N between a candidate (answer) and a reference (ground truth).

    Returns precision, recall and f1. The thesis formula
    ``Count_match / Count(reference)`` corresponds to recall; precision and f1
    are reported as well for completeness.
    """

    cand_tokens = simple_word_tokenize(candidate, fold_accents=False)
    ref_tokens = simple_word_tokenize(reference, fold_accents=False)
    cand_ngrams = _ngrams(cand_tokens, n)
    ref_ngrams = _ngrams(ref_tokens, n)

    if not ref_ngrams or not cand_ngrams:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    # Count overlapping n-grams with multiplicity (clipped).
    from collections import Counter

    cand_counts = Counter(cand_ngrams)
    ref_counts = Counter(ref_ngrams)
    overlap = sum(min(cand_counts[g], ref_counts[g]) for g in cand_counts.keys() & ref_counts.keys())

    recall = overlap / len(ref_ngrams)
    precision = overlap / len(cand_ngrams)
    return _score_triplet(precision, recall)


def rouge_l(candidate: str, reference: str, *, beta: float = 1.2) -> dict[str, float]:
    """ROUGE-L based on the Longest Common Subsequence.

    R_lcs = LCS / m  (m = reference length)
    P_lcs = LCS / n  (n = candidate length)
    F_lcs = (1 + beta^2) * R * P / (R + beta^2 * P)
    """

    cand_tokens = simple_word_tokenize(candidate, fold_accents=False)
    ref_tokens = simple_word_tokenize(reference, fold_accents=False)
    if not cand_tokens or not ref_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    lcs = _lcs_length(ref_tokens, cand_tokens)
    if lcs == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    recall = lcs / len(ref_tokens)
    precision = lcs / len(cand_tokens)
    return _score_triplet(precision, recall, beta=beta)


# ---------------------------------------------------------------------------
# LLM judge (OpenAI-compatible Chat Completions) used by RAGAS metrics
# ---------------------------------------------------------------------------

@dataclass
class LLMJudge:
    """Minimal OpenAI-compatible chat client used for LLM-as-judge metrics.

    Defaults follow the project's existing conventions. The judge is provider
    agnostic: anything exposing ``/chat/completions`` works (CodexHub/deepseek,
    Ollama, etc.).
    """

    base_url: str
    model: str
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_seconds: float = 120.0
    max_attempts: int = 4
    judge_workers: int = 1
    statement_batch_size: int = 8
    _session: Any = field(default=None, repr=False)

    @classmethod
    def from_env(cls, provider: str | None = None) -> "LLMJudge":
        """Build a judge from environment variables.

        Defaults to the project's CodexHub model (``deepseek-v4-pro``). Set
        ``provider`` or the ``RAGAS_JUDGE_PROVIDER`` env var to ``ollama`` to
        use a local Ollama endpoint instead.
        """

        load_project_env()
        requested = (provider or os.getenv("RAGAS_JUDGE_PROVIDER") or "codexhub").strip().lower()
        if requested == "auto":
            requested = "codexhub"

        if requested == "codexhub":
            api_key = os.getenv("CODEXHUB_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "CODEXHUB_API_KEY is not configured. Set it in your .env to use the "
                    "deepseek-v4-pro judge (or pass --judge-provider ollama)."
                )
            base_url = os.getenv("CODEXHUB_BASE_URL", "https://api.codexhub.click/v1").rstrip("/")
            model = os.getenv("CODEXHUB_JUDGE_MODEL", "deepseek-v4-pro")
            timeout = float(os.getenv("CODEXHUB_TIMEOUT_SECONDS", "180"))
            return cls(
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout_seconds=timeout,
                judge_workers=int(os.getenv("RAGAS_JUDGE_WORKERS", "1")),
                statement_batch_size=int(os.getenv("RAGAS_STATEMENT_BATCH_SIZE", "8")),
            )

        if requested == "ollama":
            base_url = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
            # Ollama exposes an OpenAI-compatible endpoint under /v1.
            base_url = f"{base_url}/v1"
            model = os.getenv("OLLAMA_CHAT_MODEL", "gemma4:latest")
            timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600"))
            return cls(
                base_url=base_url,
                model=model,
                api_key=None,
                timeout_seconds=timeout,
                judge_workers=int(os.getenv("RAGAS_JUDGE_WORKERS", "1")),
                statement_batch_size=int(os.getenv("RAGAS_STATEMENT_BATCH_SIZE", "8")),
            )

        raise ValueError(f"Unsupported judge provider: {requested}")

    def _get_session(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        if self.judge_workers <= 1 and self._session is not None:
            return self._session
        retry = Retry(
            total=4,
            backoff_factor=1.0,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        session.headers.update(headers)
        if self.judge_workers <= 1:
            self._session = session
        return session

    def complete(self, *, system: str, user: str) -> str:
        """Call the chat endpoint and return assistant text content."""

        session = self._get_session()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Judge request failed ({response.status_code}): "
                        f"{' '.join(response.text[:300].split())}"
                    )
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("Judge returned no choices.")
                message = choices[0].get("message") or {}
                content = message.get("content")
                if isinstance(content, list):  # some providers return content parts
                    content = "".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                content = (content or "").strip()
                if not content:
                    raise RuntimeError("Judge returned empty content.")
                return content
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.max_attempts:
                    time.sleep(min(2.0 * attempt, 10.0))
        raise RuntimeError(f"Judge call failed after {self.max_attempts} attempts: {last_exc}")

    def judge_statements_supported(
        self, *, statements: Sequence[str], context: str
    ) -> list[dict[str, Any]]:
        """For each statement decide if it is inferable from the context.

        Returns one ``{"supported": bool, "reason": str}`` per statement, so the
        caller can build a full artifact explaining *why* each statement was (or
        was not) attributed. Used by both Faithfulness (statements from the
        answer) and Context Recall (statements from the ground truth).
        """

        if not statements:
            return []
        batch_size = max(1, self.statement_batch_size)
        if self.judge_workers > 1 and len(statements) > batch_size:
            batches = [statements[i : i + batch_size] for i in range(0, len(statements), batch_size)]
            with ThreadPoolExecutor(max_workers=min(self.judge_workers, len(batches))) as executor:
                results = list(
                    executor.map(
                        lambda batch: self.judge_statements_supported(
                            statements=batch,
                            context=context,
                        ),
                        batches,
                    )
                )
            return [item for batch in results for item in batch]
        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(statements))
        system = (
            "Bạn là giám khảo đánh giá hệ thống RAG. Với mỗi câu khẳng định, hãy "
            "xác định nó có thể được suy ra hoàn toàn từ NGỮ CẢNH được cung cấp "
            "hay không. Chỉ dựa trên ngữ cảnh, không dùng kiến thức bên ngoài. "
            "Với mỗi câu hãy nêu lý do ngắn gọn bằng tiếng Việt có dấu: nếu không "
            "được hỗ trợ thì chỉ rõ thông tin nào bị thừa hoặc nằm ngoài ngữ cảnh. "
            'Trả về DUY NHẤT một đối tượng JSON dạng '
            '{"verdicts":[{"index":1,"supported":true,"reason":"..."}]}'
        )
        user = (
            f"NGỮ CẢNH:\n{context}\n\n"
            f"CÁC CÂU KHẲNG ĐỊNH:\n{numbered}\n\n"
            "Trả về JSON với một phần tử cho mỗi câu khẳng định theo đúng thứ tự, "
            "kèm lý do cho từng câu."
        )
        raw = self.complete(system=system, user=user)
        verdicts = _parse_verdicts(raw, expected=len(statements))
        return verdicts

    def generate_reverse_questions(self, *, answer: str, n: int = 3) -> list[str]:
        """Answer Relevancy step 1: generate n questions that the answer could address."""

        system = (
            "Bạn là giám khảo đánh giá hệ thống RAG. Cho một CÂU TRẢ LỜI, hãy tạo "
            "ra các câu hỏi mà câu trả lời đó giải đáp trực tiếp và đầy đủ. Các câu "
            "hỏi phải tự nhiên và viết bằng tiếng Việt có dấu. "
            'Trả về DUY NHẤT một đối tượng JSON dạng {"questions":["...","..."]}'
        )
        user = f"CÂU TRẢ LỜI:\n{answer}\n\nTạo chính xác {n} câu hỏi."
        raw = self.complete(system=system, user=user)
        questions = _parse_questions(raw)
        return questions[:n]

    def judge_chunk_relevant(
        self, *, chunk: str, question: str, answer: str
    ) -> dict[str, Any]:
        """Context Precision helper: is this chunk relevant to the question?

        Returns ``{"relevant": bool, "reason": str}`` so the artifact can show
        why a particular chunk at rank k was judged (ir)relevant.
        """

        system = (
            "Bạn là giám khảo đánh giá hệ thống RAG. Xác định đoạn NGỮ CẢNH có liên "
            "quan và hữu ích để trả lời CÂU HỎI hay không (có chứa thông tin góp "
            "phần tạo ra CÂU TRẢ LỜI). Hãy nêu lý do ngắn gọn bằng tiếng Việt có "
            "dấu: nếu không liên quan thì chỉ rõ vì sao đoạn này không hợp lý. "
            'Trả về DUY NHẤT một đối tượng JSON dạng {"relevant":true,"reason":"..."}'
        )
        user = (
            f"CÂU HỎI:\n{question}\n\n"
            f"CÂU TRẢ LỜI THAM CHIẾU:\n{answer}\n\n"
            f"ĐOẠN NGỮ CẢNH:\n{chunk}"
        )
        raw = self.complete(system=system, user=user)
        return _parse_relevant_flag(raw)


# ---------------------------------------------------------------------------
# Robust JSON parsing of judge output
# ---------------------------------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # Strip code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "co", "có", "1", "supported", "relevant"}
    return False


def _parse_verdicts(raw: str, *, expected: int) -> list[dict[str, Any]]:
    data = _extract_json(raw)
    verdicts = data.get("verdicts")
    result: list[dict[str, Any]] = [
        {"supported": False, "reason": "Giám khảo không trả về phán quyết cho câu này."}
        for _ in range(expected)
    ]
    if isinstance(verdicts, list):
        for item in verdicts:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            try:
                idx = int(idx) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < expected:
                result[idx] = {
                    "supported": _coerce_bool(item.get("supported")),
                    "reason": str(item.get("reason") or "").strip(),
                }
    return result


def _parse_questions(raw: str) -> list[str]:
    data = _extract_json(raw)
    questions = data.get("questions")
    if isinstance(questions, list):
        return [str(q).strip() for q in questions if str(q).strip()]
    return []


def _parse_relevant_flag(raw: str) -> dict[str, Any]:
    data = _extract_json(raw)
    return {
        "relevant": _coerce_bool(data.get("relevant")),
        "reason": str(data.get("reason") or "").strip(),
    }


def _preview(text: str, *, limit: int = 240) -> str:
    """Collapse whitespace and truncate a chunk for the artifact."""

    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


# ---------------------------------------------------------------------------
# RAGAS metric functions
# ---------------------------------------------------------------------------

def _statement_records(
    statements: Sequence[str],
    verdicts: Sequence[dict[str, Any]],
    *,
    flag: str,
) -> list[dict[str, Any]]:
    return [
        {"text": text, flag: bool(verdict["supported"]), "reason": verdict.get("reason", "")}
        for text, verdict in zip(statements, verdicts)
    ]


def _average_precision(relevances: Sequence[int]) -> float:
    relevant = sum(relevances)
    if relevant == 0:
        return 0.0

    hits = 0
    weighted_sum = 0.0
    for rank, value in enumerate(relevances, start=1):
        hits += value
        weighted_sum += (hits / rank) * value
    return weighted_sum / relevant


def _explain_faithfulness(score: float, total: int, unsupported: list[dict[str, Any]]) -> str:
    if not unsupported:
        return (
            f"Faithfulness = {score:.2f}: tất cả {total} câu khẳng định trong câu "
            "trả lời đều được ngữ cảnh hỗ trợ."
        )
    lines = [
        f"Faithfulness = {score:.2f}: {len(unsupported)}/{total} câu khẳng định "
        "KHÔNG được ngữ cảnh hỗ trợ (thông tin thừa / ngoài ngữ cảnh):"
    ]
    for item in unsupported:
        reason = f" — {item['reason']}" if item.get("reason") else ""
        lines.append(f"  • \"{item['text']}\"{reason}")
    return "\n".join(lines)


def faithfulness(answer: str, context: str, judge: LLMJudge) -> dict[str, Any]:
    """Faithfulness = |V| / |S|.

    S = statements in the answer, V = statements inferable from the context.
    """

    statements = split_into_statements(answer)
    if not statements:
        return {
            "score": float("nan"),
            "num_statements": 0,
            "num_supported": 0,
            "statements": [],
            "explanation": "Câu trả lời không có câu khẳng định nào để đánh giá.",
        }

    verdicts = judge.judge_statements_supported(statements=statements, context=context)
    num_supported = sum(1 for v in verdicts if v["supported"])
    score = num_supported / len(statements)
    statement_records = _statement_records(statements, verdicts, flag="supported")
    unsupported = [s for s in statement_records if not s["supported"]]
    return {
        "score": score,
        "num_statements": len(statements),
        "num_supported": num_supported,
        "statements": statement_records,
        "explanation": _explain_faithfulness(score, len(statements), unsupported),
    }


def _explain_answer_relevancy(score: float, pairs: list[tuple[str, float]]) -> str:
    # ponytail: flag generated questions below a fixed 0.7 cosine as the ones
    # dragging the mean down; good enough without a second LLM call.
    threshold = 0.7
    lines = [
        f"Answer Relevancy = {score:.2f}: trung bình cosine giữa câu hỏi gốc và "
        f"{len(pairs)} câu hỏi sinh ngược từ câu trả lời."
    ]
    weak = [(q, s) for q, s in pairs if s < threshold]
    for q, sim in pairs:
        flag = " (kém liên quan e_{q_i})" if sim < threshold else ""
        lines.append(f"  • cos={sim:.2f}{flag}: \"{q}\"")
    if weak:
        lines.append(
            f"Điểm bị kéo xuống bởi {len(weak)} câu hỏi sinh ngược lệch khỏi câu hỏi gốc."
        )
    return "\n".join(lines)


def answer_relevancy(
    question: str,
    answer: str,
    judge: LLMJudge,
    embedder: BaseEmbedder,
    *,
    n_questions: int = 3,
) -> dict[str, Any]:
    """Answer Relevancy = mean cosine(e_q, e_{q_i}) over n generated questions."""

    answer = (answer or "").strip()
    question = (question or "").strip()
    if not answer or not question:
        return {
            "score": float("nan"),
            "generated_questions": [],
            "similarities": [],
            "explanation": "Thiếu câu hỏi hoặc câu trả lời nên không tính được độ liên quan.",
        }

    generated = judge.generate_reverse_questions(answer=answer, n=n_questions)
    if not generated:
        return {
            "score": float("nan"),
            "generated_questions": [],
            "similarities": [],
            "explanation": "Không sinh được câu hỏi ngược từ câu trả lời.",
        }

    vectors = embedder.encode([question, *generated])
    q_vec = vectors[0]
    sims = [_cosine(q_vec, vectors[i + 1]) for i in range(len(generated))]
    score = float(np.mean(sims)) if sims else float("nan")
    pairs = list(zip(generated, sims))
    return {
        "score": score,
        "generated_questions": generated,
        "similarities": sims,
        "explanation": _explain_answer_relevancy(score, pairs),
    }


def _explain_context_precision(score: float, chunk_records: list[dict[str, Any]]) -> str:
    irrelevant = [c for c in chunk_records if not c["relevant"]]
    if not irrelevant:
        return (
            f"Context Precision = {score:.2f}: tất cả {len(chunk_records)} chunk trong "
            "Top-K đều liên quan đến câu hỏi/câu trả lời."
        )
    lines = [
        f"Context Precision = {score:.2f}: {len(irrelevant)}/{len(chunk_records)} chunk "
        "trong Top-K không hợp lý:"
    ]
    for c in irrelevant:
        reason = f" — {c['reason']}" if c.get("reason") else ""
        lines.append(f"  • chunk hạng {c['rank']}{reason}: \"{c['preview']}\"")
    return "\n".join(lines)


def context_precision(
    question: str,
    answer: str,
    chunks: Sequence[str],
    judge: LLMJudge,
    *,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Context Precision@K.

    sum_k (Precision@k * v_k) / (number of relevant chunks in Top-K)
    where v_k = 1 if the chunk at rank k is relevant.

    ``chunks`` must already be ordered by retrieval rank (rank 1 first).
    """

    chunks = [c for c in chunks if str(c).strip()]
    if not chunks:
        return {
            "score": float("nan"),
            "k": 0,
            "relevances": [],
            "chunks": [],
            "explanation": "Không có chunk ngữ cảnh nào để đánh giá.",
        }

    k = top_k or len(chunks)
    k = min(k, len(chunks))
    top_chunks = chunks[:k]

    if judge.judge_workers > 1 and len(top_chunks) > 1:
        with ThreadPoolExecutor(max_workers=min(judge.judge_workers, len(top_chunks))) as executor:
            judgements = list(
                executor.map(
                    lambda chunk: judge.judge_chunk_relevant(
                        chunk=chunk,
                        question=question,
                        answer=answer,
                    ),
                    top_chunks,
                )
            )
    else:
        judgements = [
            judge.judge_chunk_relevant(chunk=chunk, question=question, answer=answer)
            for chunk in top_chunks
        ]
    relevances = [1 if j["relevant"] else 0 for j in judgements]
    chunk_records = [
        {
            "rank": rank,
            "relevant": bool(j["relevant"]),
            "reason": j.get("reason", ""),
            "preview": _preview(chunk),
        }
        for rank, (chunk, j) in enumerate(zip(top_chunks, judgements), start=1)
    ]

    score = _average_precision(relevances)
    return {
        "score": score,
        "k": k,
        "relevances": relevances,
        "chunks": chunk_records,
        "explanation": _explain_context_precision(score, chunk_records),
    }


def _explain_context_recall(score: float, total: int, missing: list[dict[str, Any]]) -> str:
    if not missing:
        return (
            f"Context Recall = {score:.2f}: tất cả {total} câu trong đáp án chuẩn đều "
            "có thể quy về ngữ cảnh được truy hồi."
        )
    lines = [
        f"Context Recall = {score:.2f}: {len(missing)}/{total} câu trong đáp án chuẩn "
        "nằm NGOÀI ngữ cảnh được truy hồi:"
    ]
    for item in missing:
        reason = f" — {item['reason']}" if item.get("reason") else ""
        lines.append(f"  • \"{item['text']}\"{reason}")
    return "\n".join(lines)


def context_recall(ground_truth: str, context: str, judge: LLMJudge) -> dict[str, Any]:
    """Context Recall = |GT_attributed| / |GT|.

    GT = statements in the ground truth, GT_attributed = those inferable from
    the retrieved context.
    """

    gt_statements = split_into_statements(ground_truth)
    if not gt_statements:
        return {
            "score": float("nan"),
            "num_gt": 0,
            "num_attributed": 0,
            "statements": [],
            "explanation": "Đáp án chuẩn không có câu nào để đánh giá.",
        }

    verdicts = judge.judge_statements_supported(statements=gt_statements, context=context)
    num_attributed = sum(1 for v in verdicts if v["supported"])
    score = num_attributed / len(gt_statements)
    statement_records = _statement_records(gt_statements, verdicts, flag="attributed")
    missing = [s for s in statement_records if not s["attributed"]]
    return {
        "score": score,
        "num_gt": len(gt_statements),
        "num_attributed": num_attributed,
        "statements": statement_records,
        "explanation": _explain_context_recall(score, len(gt_statements), missing),
    }


# ---------------------------------------------------------------------------
# Dataset orchestration
# ---------------------------------------------------------------------------

@dataclass
class EvaluationConfig:
    dataset_path: Path
    output_path: Path | None = None
    limit: int | None = None
    sample_seed: int | None = None
    # Field mapping
    question_field: str = "question"
    answer_field: str = "answer"
    context_field: str = "context"
    ground_truth_field: str = "evidence_span"  # proxy ground truth for this synthetic set
    chunks_field: str | None = None  # row field holding a pre-ranked list of chunks
    id_field: str = "id"  # stable per-row key used for resume/checkpoint
    # Metric toggles
    run_faithfulness: bool = True
    run_answer_relevancy: bool = True
    run_context_precision: bool = True
    run_context_recall: bool = True
    run_rouge: bool = True
    # Knobs
    n_reverse_questions: int = 3
    embedding_backend: str = "siliconflow"
    judge_provider: str | None = None
    # Resume / checkpoint
    checkpoint_path: Path | None = None  # explicit; otherwise derived (see _resolve_checkpoint_path)
    resume: bool = True  # reuse already-computed rows from the checkpoint
    retry_errors: bool = False  # re-evaluate checkpoint rows whose previous record had an error
    cleanup_checkpoint: bool = False  # delete the checkpoint after a successful full run


def _split_context_into_chunks(context: str) -> list[str]:
    """Fallback chunking when a row has only a single context string.

    Splits on blank lines / bullet items so Context Precision has something to
    rank. With a single resulting chunk, Context Precision@K reduces to a
    hit/no-hit precision (1.0 if relevant, else 0.0).
    """

    context = canonical_unicode(context or "")
    parts = re.split(r"\n\s*\n", context)
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if part and simple_word_tokenize(part):
            chunks.append(part)
    if not chunks and context.strip():
        chunks = [context.strip()]
    return chunks


def _row_chunks(row: dict[str, Any], config: EvaluationConfig) -> list[str]:
    if config.chunks_field and isinstance(row.get(config.chunks_field), list):
        return [str(c) for c in row[config.chunks_field] if str(c).strip()]
    return _split_context_into_chunks(str(row.get(config.context_field) or ""))


def _aggregate(values: Iterable[float]) -> dict[str, float | None]:
    arr = np.array([v for v in values if v is not None and not math.isnan(v)], dtype=np.float64)
    if arr.size == 0:
        return {"mean": None, "count": 0}
    return {"mean": float(arr.mean()), "count": int(arr.size)}


def _json_safe(value: Any) -> Any:
    """Recursively convert NaN/inf floats to None so the report is valid JSON."""

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _row_key(row: dict[str, Any], config: EvaluationConfig, index: int) -> str:
    """Stable identifier for a row, used to resume from a checkpoint.

    Falls back to a content hash (and finally the row index) when the configured
    id field is missing, so resume still works on datasets without an ``id``.
    """

    raw = row.get(config.id_field)
    if raw not in (None, ""):
        return str(raw)
    import hashlib

    payload = "\u001f".join(
        str(row.get(field_name) or "")
        for field_name in (config.question_field, config.answer_field, config.context_field)
    )
    if payload.strip():
        return "sha1:" + hashlib.sha1(payload.encode("utf-8", "ignore")).hexdigest()
    return f"index:{index}"


def _resolve_checkpoint_path(config: EvaluationConfig) -> Path | None:
    """Where to read/write incremental progress.

    Priority: explicit ``checkpoint_path`` > ``<output_path>.partial.jsonl`` >
    None (no checkpointing when neither output nor checkpoint is set).
    """

    if config.checkpoint_path is not None:
        return config.checkpoint_path
    if config.output_path is not None:
        return config.output_path.with_suffix(config.output_path.suffix + ".partial.jsonl")
    return None


def _load_checkpoint(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load previously computed per-row records keyed by ``_key``."""

    records: dict[str, dict[str, Any]] = {}
    if path is None or not path.exists():
        return records
    for record in iter_jsonl(path):
        key = record.get("_key")
        if key is not None:
            records[str(key)] = record
    return records


def _evaluate_row(
    row: dict[str, Any],
    config: EvaluationConfig,
    judge: LLMJudge | None,
    embedder: BaseEmbedder | None,
) -> dict[str, Any]:
    """Compute all enabled metrics for a single row."""

    question = str(row.get(config.question_field) or "")
    answer = str(row.get(config.answer_field) or "")
    context = str(row.get(config.context_field) or "")
    ground_truth = str(row.get(config.ground_truth_field) or "") or context

    record: dict[str, Any] = {
        "id": row.get("id"),
        "source_url": row.get("source_url") or row.get("source"),
        "question": question,
    }

    try:
        if config.run_faithfulness:
            record["faithfulness"] = faithfulness(answer, context, judge)  # type: ignore[arg-type]
        if config.run_answer_relevancy:
            record["answer_relevancy"] = answer_relevancy(
                question, answer, judge, embedder, n_questions=config.n_reverse_questions  # type: ignore[arg-type]
            )
        if config.run_context_precision:
            chunks = _row_chunks(row, config)
            record["context_precision"] = context_precision(question, answer, chunks, judge)  # type: ignore[arg-type]
        if config.run_context_recall:
            record["context_recall"] = context_recall(ground_truth, context, judge)  # type: ignore[arg-type]
        if config.run_rouge:
            record["rouge_1"] = rouge_n(answer, ground_truth, n=1)
            record["rouge_2"] = rouge_n(answer, ground_truth, n=2)
            record["rouge_l"] = rouge_l(answer, ground_truth)
        record["error"] = None
    except Exception as exc:  # noqa: BLE001
        record["error"] = str(exc)

    return record


def _build_summary(
    config: EvaluationConfig,
    per_row: list[dict[str, Any]],
    judge: LLMJudge | None,
) -> dict[str, Any]:
    aggregates = {
        "faithfulness": _aggregate(
            r["faithfulness"]["score"] for r in per_row if "faithfulness" in r
        ),
        "answer_relevancy": _aggregate(
            r["answer_relevancy"]["score"] for r in per_row if "answer_relevancy" in r
        ),
        "context_precision": _aggregate(
            r["context_precision"]["score"] for r in per_row if "context_precision" in r
        ),
        "context_recall": _aggregate(
            r["context_recall"]["score"] for r in per_row if "context_recall" in r
        ),
        "rouge_1_f1": _aggregate(r["rouge_1"]["f1"] for r in per_row if "rouge_1" in r),
        "rouge_2_f1": _aggregate(r["rouge_2"]["f1"] for r in per_row if "rouge_2" in r),
        "rouge_l_f1": _aggregate(r["rouge_l"]["f1"] for r in per_row if "rouge_l" in r),
    }
    return {
        "dataset_path": str(config.dataset_path),
        "evaluated_rows": len(per_row),
        "rows_with_errors": sum(1 for r in per_row if r.get("error")),
        "embedding_backend": config.embedding_backend if config.run_answer_relevancy else None,
        "judge": {"model": judge.model, "endpoint": judge.base_url} if judge else None,
        "field_mapping": {
            "question": config.question_field,
            "answer": config.answer_field,
            "context": config.context_field,
            "ground_truth": config.ground_truth_field,
            "chunks": config.chunks_field or "<context split into paragraphs>",
        },
        "aggregates": aggregates,
    }


def _select_rows(config: EvaluationConfig) -> list[dict[str, Any]]:
    rows = list(iter_jsonl(config.dataset_path))
    if config.sample_seed is not None and config.limit and config.limit < len(rows):
        rng = np.random.default_rng(config.sample_seed)
        indices = sorted(rng.choice(len(rows), size=config.limit, replace=False).tolist())
        return [rows[i] for i in indices]
    if config.limit is not None:
        return rows[: config.limit]
    return rows


def evaluate_dataset(
    config: EvaluationConfig,
    *,
    progress: Callable[[int, int], None] | None = None,
    judge: LLMJudge | None = None,
    embedder: BaseEmbedder | None = None,
) -> dict[str, Any]:
    """Evaluate every row of a QA dataset and return per-row + aggregate scores.

    Resilience features:
      * ``config.resume`` reuses rows already present in the checkpoint file so a
        re-run only computes what is missing.
      * Each freshly computed row is appended to the checkpoint immediately, so a
        crash mid-run loses at most one row of work.
      * ``config.retry_errors`` recomputes checkpoint rows whose prior record had
        a non-null ``error``.

    ``judge`` / ``embedder`` may be passed in to share clients across many files
    (see :func:`evaluate_datasets`); otherwise they are built on demand.
    """

    load_project_env()
    rows = _select_rows(config)

    needs_judge = (
        config.run_faithfulness
        or config.run_answer_relevancy
        or config.run_context_precision
        or config.run_context_recall
    )
    if needs_judge and judge is None:
        judge = LLMJudge.from_env(config.judge_provider)
    if config.run_answer_relevancy and embedder is None:
        embedder = build_embedder(config.embedding_backend)

    checkpoint_path = _resolve_checkpoint_path(config)
    cached = _load_checkpoint(checkpoint_path) if config.resume else {}

    # Open the checkpoint for appending new rows as they complete.
    checkpoint_handle = None
    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_handle = checkpoint_path.open("a", encoding="utf-8")

    per_row: list[dict[str, Any]] = []
    total = len(rows)
    reused = 0
    try:
        for index, row in enumerate(rows):
            key = _row_key(row, config, index)
            cached_record = cached.get(key)
            use_cached = (
                cached_record is not None
                and not (config.retry_errors and cached_record.get("error"))
            )
            if use_cached:
                record = {k: v for k, v in cached_record.items() if k != "_key"}
                reused += 1
            else:
                record = _evaluate_row(row, config, judge, embedder)
                if checkpoint_handle is not None:
                    checkpoint_handle.write(
                        json.dumps(_json_safe({"_key": key, **record}), ensure_ascii=False) + "\n"
                    )
                    checkpoint_handle.flush()
            per_row.append(record)
            if progress:
                progress(index + 1, total)
    finally:
        if checkpoint_handle is not None:
            checkpoint_handle.close()

    summary = _build_summary(config, per_row, judge)
    summary["resumed_rows"] = reused
    summary["checkpoint_path"] = str(checkpoint_path) if checkpoint_path else None

    result = _json_safe({"summary": summary, "results": per_row})

    if config.output_path:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        with config.output_path.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)

    # Only remove the checkpoint once the final report is safely written.
    if (
        config.cleanup_checkpoint
        and checkpoint_path is not None
        and checkpoint_path.exists()
        and config.output_path is not None
    ):
        try:
            checkpoint_path.unlink()
        except OSError:
            pass

    return result


def evaluate_datasets(
    configs: Sequence[EvaluationConfig],
    *,
    progress: Callable[[int, int], None] | None = None,
    file_progress: Callable[[int, int, Path], None] | None = None,
) -> dict[str, Any]:
    """Evaluate multiple QA files, sharing one judge + embedder across all of them.

    The judge/embedder are built once from the first config that needs them and
    reused, which avoids repeated client setup and respects rate limits. Each
    file is checkpointed and reported independently, so a failure on one file
    does not discard completed files.
    """

    load_project_env()
    shared_judge: LLMJudge | None = None
    shared_embedder: BaseEmbedder | None = None

    per_file: dict[str, Any] = {}
    errors: dict[str, str] = {}
    total_files = len(configs)
    for file_index, config in enumerate(configs):
        if file_progress:
            file_progress(file_index + 1, total_files, config.dataset_path)

        needs_judge = (
            config.run_faithfulness
            or config.run_answer_relevancy
            or config.run_context_precision
            or config.run_context_recall
        )
        if needs_judge and shared_judge is None:
            shared_judge = LLMJudge.from_env(config.judge_provider)
        if config.run_answer_relevancy and shared_embedder is None:
            shared_embedder = build_embedder(config.embedding_backend)

        try:
            result = evaluate_dataset(
                config,
                progress=progress,
                judge=shared_judge,
                embedder=shared_embedder,
            )
            per_file[str(config.dataset_path)] = result["summary"]
        except Exception as exc:  # noqa: BLE001
            # Keep going so one bad file doesn't sink the whole batch.
            errors[str(config.dataset_path)] = str(exc)

    return {
        "files_evaluated": len(per_file),
        "files_failed": len(errors),
        "summaries": per_file,
        "errors": errors,
    }
