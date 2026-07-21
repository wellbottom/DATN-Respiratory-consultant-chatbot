from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from scripts.RAG.embedding import BaseEmbedder, build_embedder
from scripts.RAG.generator import RequestLLMClient
from scripts.RAG.retriever import DEFAULT_RRF_K, HybridIndex, reciprocal_rank_fusion
from scripts.RAG.source_metadata import SourceUrlResolver
from urllib3.util.retry import Retry

from .chroma_store import ChromaConnectionConfig, build_chroma_client, get_collection, parse_query_results
from .settings import AppSettings
from .text_utils import iter_jsonl

MAX_HISTORY_TURNS = 10
MAX_PROMPT_HISTORY_TURNS = 8
MAX_CONTEXTUALIZATION_TURNS = 6
MAX_HISTORY_MESSAGE_CHARS = 1200
MAX_RETRIEVAL_QUERY_CHARS = 400
MAX_DIAGNOSTIC_QUERY_CHARS = 600
GENERAL_KNOWLEDGE_BASE = "general_medical"


@dataclass(slots=True)
class QueryPlan:
    collection_name: str
    knowledge_base: str
    corpora: list[str]
    intent: str
    section_types: list[str]
    reasons: list[str]


@dataclass(slots=True)
class CandidateResult:
    chunk_id: str
    document: str
    metadata: dict[str, Any]
    vector_score: float
    vector_distance: float
    retrieved_from: str
    rerank_score: float | None = None
    bm25_score: float = 0.0
    rrf_score: float = 0.0


@dataclass(slots=True)
class SectionBundle:
    section_id: str
    corpus: str
    title: str
    h2: str | None
    h3: str | None
    section_type: str
    source_path: str
    source_url: str | None
    source_url_kind: str | None
    rerank_score: float | None
    vector_score: float | None
    vector_distance: float | None
    chunks: list[dict[str, Any]]
    text: str
    bm25_score: float = 0.0
    rrf_score: float = 0.0


def source_section_payload(section: SectionBundle) -> dict[str, Any]:
    return {
        "section_id": section.section_id,
        "corpus": section.corpus,
        "title": section.title,
        "h2": section.h2,
        "h3": section.h3,
        "section_type": section.section_type,
        "source_path": section.source_path,
        "source_url": section.source_url,
        "source_url_kind": section.source_url_kind,
        "rerank_score": section.rerank_score,
        "vector_score": section.vector_score,
        "vector_distance": section.vector_distance,
        "bm25_score": section.bm25_score,
        "rrf_score": section.rrf_score,
        "chunk_count": len(section.chunks),
        "chunks": section.chunks,
    }


class RetrievalEngine:
    def __init__(
        self,
        settings: AppSettings,
        *,
        collection_name: str | None = None,
        knowledge_base: str = GENERAL_KNOWLEDGE_BASE,
    ) -> None:
        self.settings = settings
        self.collection_name = (collection_name or settings.chroma_collection_name).strip()
        self.knowledge_base = knowledge_base
        self.source_url_resolver = SourceUrlResolver()
        self.chroma_config = ChromaConnectionConfig(
            mode=settings.chroma_mode,
            collection_name=self.collection_name,
            persist_path=settings.chroma_persist_path,
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            http_host=settings.chroma_http_host,
            http_port=settings.chroma_http_port,
            http_ssl=settings.chroma_http_ssl,
            http_headers=settings.chroma_http_headers,
            cloud_api_key=settings.chroma_cloud_api_key,
            cloud_host=settings.chroma_cloud_host,
            cloud_port=settings.chroma_cloud_port,
            cloud_ssl=settings.chroma_cloud_ssl,
        )

        self.client = build_chroma_client(self.chroma_config)
        self.collection = get_collection(self.client, self.chroma_config.collection_name)
        self.collection_metadata = dict(getattr(self.collection, "metadata", {}) or {})
        self.distance_space = str(self.collection_metadata.get("distance_space") or "cosine")
        self.rerank_session = self._build_rerank_session()
        self.embedder = self._build_query_embedder()
        self.hybrid_index = (
            HybridIndex(settings.hybrid_index_dir)
            if (settings.hybrid_index_dir / "manifest.json").exists()
            else None
        )
        self.section_store_path = self._resolve_section_store_path()
        self.legacy_flat_chunks = False
        self.section_index = self._load_section_index()

    @staticmethod
    def _build_rerank_session() -> requests.Session:
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            backoff_factor=1.0,
            status_forcelist=[408, 429, 500, 502, 503, 504, 520, 521, 522, 524],
            allowed_methods=["POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _build_query_embedder(self) -> BaseEmbedder:
        embedding_backend = str(self.collection_metadata.get("embedding_backend") or "siliconflow").strip().lower()
        return build_embedder(
            embedding_backend or "siliconflow",
            dimension=int(self.collection_metadata.get("embedding_dimension") or self.settings.embedding_dimension),
            model_name=str(self.collection_metadata.get("embedding_model_name") or self.settings.embedding_model_name),
            endpoint=str(self.collection_metadata.get("embedding_endpoint") or self.settings.embedding_endpoint),
            api_key_env=str(self.collection_metadata.get("embedding_api_key_env") or "SILICONFLOW_API_KEY"),
            timeout_seconds=float(
                self.collection_metadata.get("embedding_timeout_seconds") or self.settings.embedding_timeout_seconds
            ),
            max_batch_size=int(
                self.collection_metadata.get("embedding_max_batch_size") or self.settings.embedding_max_batch_size
            ),
        )

    def _resolve_section_store_path(self) -> Path | None:
        if self.settings.section_store_path is not None:
            path = self.settings.section_store_path.resolve()
            if path.exists():
                return path
            if self.settings.chroma_mode != "cloud":
                raise FileNotFoundError(f"WEBAPP_SECTION_STORE_PATH khÃ´ng tá»“n táº¡i: {path}")

        chunks_path_value = self.collection_metadata.get("chunks_path")
        if chunks_path_value:
            path = Path(str(chunks_path_value)).expanduser().resolve()
            if path.exists():
                return path

        if self.settings.chroma_mode == "cloud":
            return None

        raise RuntimeError(
            "KhÃ´ng xÃ¡c Ä‘á»‹nh Ä‘Æ°á»£c section store Ä‘á»ƒ má»Ÿ rá»™ng ná»™i dung. "
            "HÃ£y Ä‘áº·t WEBAPP_SECTION_STORE_PATH trá» tá»›i file chunks.jsonl khá»›p vá»›i collection Chroma Ä‘ang dÃ¹ng."
        )

    def _load_section_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        if self.section_store_path is None:
            return index
        for row in iter_jsonl(self.section_store_path):
            if "section_id" not in row:
                self.legacy_flat_chunks = True
                chunk_id = str(row.get("chunk_id") or row.get("content_hash") or f"chunk-{len(index)}")
                source_path = str(row.get("source_path") or row.get("source_file") or "")
                index[chunk_id] = {
                    "section_id": chunk_id,
                    "corpus": str(row.get("corpus") or self.collection_name),
                    "title": str(row.get("title") or source_path or "Respiratory source"),
                    "h2": row.get("h2"),
                    "h3": row.get("h3"),
                    "section_type": str(row.get("section_type") or row.get("type") or "article_section"),
                    "source_path": source_path,
                    "source_url": row.get("source_url"),
                    "source_url_kind": row.get("source_url_kind"),
                    "chunks": [
                        {
                            "chunk_id": chunk_id,
                            "candidate_chunk_index": int(row.get("candidate_chunk_index") or 1),
                            "candidate_chunk_total": int(row.get("candidate_chunk_total") or 1),
                            "content": str(row.get("content") or row.get("text") or ""),
                        }
                    ],
                }
                continue
            section_id = str(row["section_id"])
            entry = index.setdefault(
                section_id,
                {
                    "section_id": section_id,
                    "corpus": row["corpus"],
                    "title": row["title"],
                    "h2": row.get("h2"),
                    "h3": row.get("h3"),
                    "section_type": row["section_type"],
                    "source_path": row["source_path"],
                    "source_url": row.get("source_url"),
                    "source_url_kind": row.get("source_url_kind"),
                    "chunks": [],
                },
            )
            entry["chunks"].append(
                {
                    "chunk_id": row["chunk_id"],
                    "candidate_chunk_index": int(row["candidate_chunk_index"]),
                    "candidate_chunk_total": int(row["candidate_chunk_total"]),
                    "content": row["content"],
                }
            )

        for entry in index.values():
            entry["chunks"].sort(key=lambda item: item["candidate_chunk_index"])
        return index

    def _query_collection(self, query_vector: list[float], *, where: dict[str, Any] | None, top_k: int) -> list[CandidateResult]:
        query_args: dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": max(1, int(top_k)),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_args["where"] = where
        payload = self.collection.query(**query_args)
        parsed = parse_query_results(payload, distance_space=self.distance_space)
        return [
            CandidateResult(
                chunk_id=item["chunk_id"],
                document=item["document"],
                metadata=item["metadata"],
                vector_score=float(item["score"]),
                vector_distance=float(item["distance"]),
                retrieved_from=str(item["metadata"].get("corpus") or "unknown"),
            )
            for item in parsed
        ]

    def search(self, query: str, *, retrieval_query: str | None = None) -> tuple[QueryPlan, list[CandidateResult]]:
        query_text = (retrieval_query or query).strip() or query
        query_vector = self.embedder.encode_queries([query_text])[0]
        pool = self.settings.rerank_candidate_limit
        dense = self._query_collection(query_vector, where=None, top_k=pool)
        if self.hybrid_index is None:
            plan = QueryPlan(
                collection_name=self.collection_name,
                knowledge_base=self.knowledge_base,
                corpora=["local_rag"],
                intent="general",
                section_types=[],
                reasons=[f"Vector retrieval from Chroma collection {self.collection_name}."],
            )
            return plan, dense

        lexical_hits = self.hybrid_index.lexical_search(query_text, top_k=pool)
        lexical = {
            str(self.hybrid_index.chunks[doc_idx]["chunk_id"]): (self.hybrid_index.chunks[doc_idx], score)
            for doc_idx, score in lexical_hits
        }

        candidates = {candidate.chunk_id: candidate for candidate in dense}
        for chunk_id, (chunk, score) in lexical.items():
            candidate = candidates.get(chunk_id)
            if candidate is None:
                candidate = CandidateResult(
                    chunk_id=chunk_id,
                    document=str(chunk.get("content") or chunk.get("text") or ""),
                    metadata=dict(chunk),
                    vector_score=0.0,
                    vector_distance=1.0,
                    retrieved_from=str(chunk.get("corpus") or "local_rag"),
                )
                candidates[chunk_id] = candidate
            candidate.bm25_score = float(score)

        chunk_ids = list(candidates)
        positions = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        fused = reciprocal_rank_fusion(
            [
                [positions[candidate.chunk_id] for candidate in dense],
                [positions[str(self.hybrid_index.chunks[doc_idx]["chunk_id"])] for doc_idx, _ in lexical_hits],
            ],
            rrf_k=DEFAULT_RRF_K,
        )[:pool]
        ranked = []
        for position, score in fused:
            candidate = candidates[chunk_ids[position]]
            candidate.rrf_score = score
            ranked.append(candidate)

        plan = QueryPlan(
            collection_name=self.collection_name,
            knowledge_base=self.knowledge_base,
            corpora=["local_rag"],
            intent="general",
            section_types=[],
            reasons=["Hybrid retrieval over the complete local_rag collection."],
        )
        return plan, ranked

    def rerank(self, query: str, candidates: list[CandidateResult]) -> list[CandidateResult]:
        if not candidates:
            return []

        response = self.rerank_session.post(
            self.settings.reranker_url,
            headers={
                "Authorization": f"Bearer {self.settings.siliconflow_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.reranker_model,
                "query": query,
                "documents": [candidate.document for candidate in candidates],
                "top_n": len(candidates),
                "return_documents": False,
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

        reranked: list[CandidateResult] = []
        for item in data.get("results", []):
            index = int(item["index"])
            candidate = candidates[index]
            reranked.append(
                CandidateResult(
                    chunk_id=candidate.chunk_id,
                    document=candidate.document,
                    metadata=candidate.metadata,
                    vector_score=candidate.vector_score,
                    vector_distance=candidate.vector_distance,
                    retrieved_from=candidate.retrieved_from,
                    rerank_score=float(item["relevance_score"]),
                    bm25_score=candidate.bm25_score,
                    rrf_score=candidate.rrf_score,
                )
            )

        return reranked or candidates

    @staticmethod
    def _render_section_text(section: dict[str, Any]) -> str:
        blocks = [f"# {section['title']}"]
        if section.get("h2"):
            blocks.append(f"## {section['h2']}")
        if section.get("h3"):
            blocks.append(f"### {section['h3']}")
        for chunk in section["chunks"]:
            blocks.append(str(chunk["content"]).strip())
        return "\n\n".join(block for block in blocks if block).strip()

    def expand_sections(self, candidates: list[CandidateResult]) -> list[SectionBundle]:
        selected: list[SectionBundle] = []
        seen_section_ids: set[str] = set()
        current_characters = 0

        for candidate in candidates:
            section_id = str(candidate.metadata.get("section_id") or candidate.chunk_id)
            if section_id in seen_section_ids:
                continue

            section = self.section_index.get(section_id)
            if section is None:
                source_url_resolution = self.source_url_resolver.resolve(
                    source_path=candidate.metadata.get("source_path"),
                    title=candidate.metadata.get("title"),
                    existing_url=candidate.metadata.get("source_url"),
                    existing_url_kind=candidate.metadata.get("source_url_kind"),
                )
                section = {
                    "section_id": section_id,
                    "corpus": candidate.metadata.get("corpus", "unknown"),
                    "title": candidate.metadata.get("title", "Unknown source"),
                    "h2": candidate.metadata.get("h2"),
                    "h3": candidate.metadata.get("h3"),
                    "section_type": candidate.metadata.get("section_type", "article_section"),
                    "source_path": candidate.metadata.get("source_path", ""),
                    "source_url": source_url_resolution.source_url,
                    "source_url_kind": source_url_resolution.source_url_kind,
                    "chunks": [
                        {
                            "chunk_id": candidate.chunk_id,
                            "candidate_chunk_index": int(candidate.metadata.get("candidate_chunk_index", 1)),
                            "candidate_chunk_total": int(candidate.metadata.get("candidate_chunk_total", 1)),
                            "content": candidate.document,
                        }
                    ],
                }

            rendered_text = self._render_section_text(section)
            if (
                self.settings.max_context_characters > 0
                and selected
                and current_characters + len(rendered_text) > self.settings.max_context_characters
            ):
                break

            selected.append(
                SectionBundle(
                    section_id=section_id,
                    corpus=str(section["corpus"]),
                    title=str(section["title"]),
                    h2=section.get("h2"),
                    h3=section.get("h3"),
                    section_type=str(section["section_type"]),
                    source_path=str(section["source_path"]),
                    source_url=str(section.get("source_url") or "") or None,
                    source_url_kind=str(section.get("source_url_kind") or "") or None,
                    rerank_score=candidate.rerank_score,
                    vector_score=candidate.vector_score,
                    vector_distance=candidate.vector_distance,
                    chunks=[
                        {
                            "chunk_id": chunk["chunk_id"],
                            "candidate_chunk_index": int(chunk["candidate_chunk_index"]),
                            "candidate_chunk_total": int(chunk["candidate_chunk_total"]),
                            "content": str(chunk.get("content") or ""),
                        }
                        for chunk in section["chunks"]
                    ],
                    text=rendered_text,
                    bm25_score=candidate.bm25_score,
                    rrf_score=candidate.rrf_score,
                )
            )
            seen_section_ids.add(section_id)
            current_characters += len(rendered_text)

            if len(selected) >= self.settings.final_section_limit:
                break

        return selected

    def build_medical_context(self, sections: list[SectionBundle]) -> str:
        blocks: list[str] = []
        for index, section in enumerate(sections, start=1):
            reference_value = section.source_url or section.source_path
            blocks.append(
                "\n".join(
                    [
                        f"[Source {index}]",
                        f"Corpus: {section.corpus}",
                        f"Section type: {section.section_type}",
                        f"Source reference: {reference_value}",
                        "Medical content:",
                        section.text,
                    ]
                )
            )
        return "\n\n".join(blocks).strip()


class MedicalAssistantService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.retrieval = RetrievalEngine(settings, collection_name="local_rag", knowledge_base=GENERAL_KNOWLEDGE_BASE)
        self.llm = RequestLLMClient.from_settings(settings)

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip() + "..."

    def _prepare_history(self, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
        sanitized: list[dict[str, str]] = []
        for turn in history or []:
            role = str(turn.get("role") or "").strip()
            content = str(turn.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            sanitized.append(
                {
                    "role": role,
                    "content": self._truncate_text(content, MAX_HISTORY_MESSAGE_CHARS),
                }
            )
        return sanitized[-MAX_HISTORY_TURNS:]

    @staticmethod
    def _format_history(history: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for turn in history:
            speaker = "NgÆ°á»i dÃ¹ng" if turn["role"] == "user" else "Trá»£ lÃ½"
            lines.append(f"{speaker}: {turn['content']}")
        return "\n".join(lines).strip()

    def _build_fallback_contextual_query(self, *, user_query: str, history: list[dict[str, str]]) -> str:
        recent_user_turns = [turn["content"] for turn in history if turn["role"] == "user"][-2:]
        if not recent_user_turns:
            return user_query
        prior_context = " | ".join(recent_user_turns)
        fallback = f"{user_query}. Ngá»¯ cáº£nh liÃªn quan trÆ°á»›c Ä‘Ã³: {prior_context}"
        return self._truncate_text(fallback, MAX_RETRIEVAL_QUERY_CHARS)

    @staticmethod
    def _describe_requests_error(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is not None:
            preview = " ".join(str(response.text or "").split())
            if preview:
                return f"{response.status_code}: {preview[:280]}"
            return f"{response.status_code}: {response.reason}"
        return str(exc)

    def _answer_with_context_fallback(
        self,
        *,
        retrieval: RetrievalEngine,
        user_query: str,
        sections: list[SectionBundle],
        conversation_context: str,
        contextual_query: str,
    ) -> tuple[str, list[SectionBundle], str, str | None]:
        section_variants: list[tuple[list[SectionBundle], str]] = []
        for count in (len(sections), min(len(sections), 2), 1):
            if count <= 0:
                continue
            strategy = f"top-{count}-sections"
            if any(existing_strategy == strategy for _, existing_strategy in section_variants):
                continue
            section_variants.append((sections[:count], strategy))

        fallback_error: str | None = None
        char_fallback_limits = (self.settings.max_context_characters, 4500, 3000, 2000)

        for section_subset, base_strategy in section_variants:
            base_context = retrieval.build_medical_context(section_subset)
            if not base_context:
                continue

            char_limits: list[int] = []
            for limit in (len(base_context), *char_fallback_limits):
                bounded = max(600, min(len(base_context), int(limit)))
                if bounded not in char_limits:
                    char_limits.append(bounded)

            for limit in char_limits:
                if limit >= len(base_context):
                    candidate_context = base_context
                    strategy = f"{base_strategy}-full"
                else:
                    candidate_context = self._truncate_text(base_context, limit)
                    strategy = f"{base_strategy}-trim-{limit}"

                try:
                    answer = self.llm.answer_clean(
                        user_query=user_query,
                        medical_context=candidate_context,
                        conversation_context=conversation_context,
                        contextual_query=contextual_query,
                    )
                    return answer, section_subset, strategy, fallback_error
                except Exception as exc:  # noqa: BLE001
                    if self.llm.is_request_too_large(exc):
                        fallback_error = self.llm.describe_error(exc)
                        continue
                    raise

        if fallback_error is not None:
            raise RuntimeError(fallback_error)
        raise RuntimeError("Mo hinh chat khong tra ve cau tra loi hop le.")

    def _resolve_retrieval_query(self, *, user_query: str, history: list[dict[str, str]]) -> tuple[str, str, str | None]:
        if not history:
            return user_query, "current-turn-only", None

        contextualization_history = history[-MAX_CONTEXTUALIZATION_TURNS:]
        conversation_context = self._format_history(contextualization_history)

        try:
            rewritten = self.llm.contextualize_query_clean(
                user_query=user_query,
                conversation_context=conversation_context,
            )
            if rewritten:
                return self._truncate_text(rewritten, MAX_RETRIEVAL_QUERY_CHARS), "llm-rewrite", None
        except Exception as exc:  # noqa: BLE001
            fallback = self._build_fallback_contextual_query(user_query=user_query, history=contextualization_history)
            return fallback, "heuristic-fallback", str(exc)

        fallback = self._build_fallback_contextual_query(user_query=user_query, history=contextualization_history)
        return fallback, "heuristic-fallback", "CPAB contextualizer returned an empty query."

    def chat(self, user_query: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        sanitized_history = self._prepare_history(history)
        prompt_history = sanitized_history[-MAX_PROMPT_HISTORY_TURNS:]
        conversation_context = self._format_history(prompt_history) or "KhÃ´ng cÃ³ lá»‹ch sá»­ há»™i thoáº¡i trÆ°á»›c Ä‘Ã³."

        retrieval_query, contextualization_strategy, contextualization_error = self._resolve_retrieval_query(
            user_query=user_query,
            history=sanitized_history,
        )
        retrieval_engine = self.retrieval
        plan, retrieved = retrieval_engine.search(user_query, retrieval_query=retrieval_query)
        rerank_error: str | None = None
        try:
            reranked = retrieval_engine.rerank(retrieval_query, retrieved)
        except requests.RequestException as exc:
            rerank_error = self._describe_requests_error(exc)
            reranked = retrieved
        except Exception as exc:  # noqa: BLE001
            rerank_error = str(exc)
            reranked = retrieved
        sections = retrieval_engine.expand_sections(reranked)
        medical_context = retrieval_engine.build_medical_context(sections)

        if not medical_context:
            answer = (
                "TÃ´i chÆ°a tÃ¬m tháº¥y ngá»¯ cáº£nh y khoa Ä‘á»§ liÃªn quan trong cÆ¡ sá»Ÿ dá»¯ liá»‡u hiá»‡n táº¡i Ä‘á»ƒ tráº£ lá»i an toÃ n. "
                "Báº¡n cÃ³ thá»ƒ diá»…n Ä‘áº¡t rÃµ hÆ¡n vá» bá»‡nh, triá»‡u chá»©ng, Ä‘á»™ tuá»•i hoáº·c Ä‘á»‘i tÆ°á»£ng cáº§n há»i."
            )
            answer_sections = sections
            answer_context_strategy = "no-medical-context"
            answer_context = ""
            answer_context_error = None
        else:
            answer, answer_sections, answer_context_strategy, answer_context_error = self._answer_with_context_fallback(
                retrieval=retrieval_engine,
                user_query=user_query,
                sections=sections,
                conversation_context=conversation_context,
                contextual_query=retrieval_query,
            )
            answer_context = retrieval_engine.build_medical_context(answer_sections)

        diagnostics: dict[str, Any] = {
            "retrieved_candidate_count": len(retrieved),
            "reranked_candidate_count": len(reranked),
            "selected_section_count": len(sections),
            "answer_section_count": len(answer_sections),
            "context_characters": len(answer_context),
            "retrieval_context_characters": len(medical_context),
            "reranker_model": self.settings.reranker_model,
            "chat_provider_order": self.llm.provider_order(),
            "chat_primary_model": self.settings.llm_model,
            "chat_primary_endpoint": self.settings.llm_providers[0]["endpoint"],
            "history_turn_count": len(sanitized_history),
            "prompt_history_turn_count": len(prompt_history),
            "retrieval_query": self._truncate_text(retrieval_query, MAX_DIAGNOSTIC_QUERY_CHARS),
            "contextualization_strategy": contextualization_strategy,
            "answer_context_strategy": answer_context_strategy,
            "chroma_mode": self.settings.chroma_mode,
            "chroma_collection": plan.collection_name,
            "knowledge_base": retrieval_engine.knowledge_base,
            "embedding_backend": retrieval_engine.collection_metadata.get("embedding_backend"),
        }
        if contextualization_error:
            diagnostics["contextualization_error"] = contextualization_error[:300]
        if rerank_error:
            diagnostics["rerank_error"] = rerank_error[:300]
            diagnostics["rerank_fallback_used"] = True
        if answer_context_error:
            diagnostics["answer_context_error"] = answer_context_error[:300]
        return {
            "answer": answer,
            "route": {
                "collection_name": plan.collection_name,
                "knowledge_base": plan.knowledge_base,
                "corpora": plan.corpora,
                "intent": plan.intent,
                "section_types": plan.section_types,
                "reasons": plan.reasons,
            },
            "sources": [
                source_section_payload(section) for section in answer_sections
            ],
            "diagnostics": diagnostics,
        }

