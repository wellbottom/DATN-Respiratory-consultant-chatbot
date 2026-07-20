from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Literal, Sequence

import numpy as np
import requests

from .common import configure_utf8_stdio, iter_jsonl, load_project_env, simple_word_tokenize
from .embedding import build_embedder
from .indexing import build_dense_text


RETRIEVAL_MODES = ("vector", "bm25", "hybrid", "hybrid_rerank")
RetrievalMode = Literal["vector", "bm25", "hybrid", "hybrid_rerank"]
DEFAULT_RRF_K = 60
DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-8B"
DEFAULT_RERANKER_URL = "https://api.siliconflow.com/v1/rerank"


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[int]],
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, doc_idx in enumerate(ranked, start=1):
            scores[int(doc_idx)] = scores.get(int(doc_idx), 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _self_check_rrf() -> None:
    # ponytail: O(n) over tiny rank lists; upgrade path is weighted RRF if needed.
    fused = reciprocal_rank_fusion([[0, 1, 2], [2, 0, 1]], rrf_k=60)
    assert [doc_idx for doc_idx, _ in fused] == [0, 2, 1]
    assert fused[0][1] > fused[-1][1]


class HybridIndex:
    def __init__(self, index_dir: Path) -> None:
        load_project_env()
        self.index_dir = index_dir
        self.manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        self.chunks = list(iter_jsonl(index_dir / "chunks.jsonl"))
        self.vectors = np.load(index_dir / "vectors.npy", mmap_mode="r")
        lexical_uri = f"file:{(index_dir / 'lexical.sqlite3').resolve().as_posix()}?mode=ro"
        self.connection = sqlite3.connect(lexical_uri, uri=True, check_same_thread=False)
        dense = self.manifest["dense"]["embedding"]
        self.embedder = build_embedder(
            dense["backend"],
            dimension=int(dense["dimension"]) if dense.get("dimension") is not None else None,
            model_name=dense.get("model_name"),
            use_bigrams=bool(dense["use_bigrams"]) if dense.get("use_bigrams") is not None else None,
            endpoint=dense.get("endpoint"),
            api_key_env=dense.get("api_key_env", "SILICONFLOW_API_KEY"),
            timeout_seconds=float(dense["timeout_seconds"]) if dense.get("timeout_seconds") is not None else None,
            max_batch_size=int(dense["max_batch_size"]) if dense.get("max_batch_size") is not None else None,
        )
        self.avgdl = float(self.manifest["lexical"]["avgdl"])
        self.k1 = float(self.manifest["lexical"]["k1"])
        self.b = float(self.manifest["lexical"]["b"])

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _chunk_document(chunk: dict) -> str:
        return build_dense_text(chunk)

    def _format_hits(
        self,
        hits: list[tuple[int, float]],
        *,
        score_key: str = "score",
        extra_fields: dict[int, dict[str, float]] | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        for doc_idx, score in hits:
            row = dict(self.chunks[doc_idx])
            row[score_key] = score
            if extra_fields and doc_idx in extra_fields:
                row.update(extra_fields[doc_idx])
            results.append(row)
        return results

    def lexical_search(self, query: str, *, top_k: int = 10) -> list[tuple[int, float]]:
        query_terms = simple_word_tokenize(query, fold_accents=True)
        if not query_terms:
            return []

        scores: dict[int, float] = {}
        cursor = self.connection.cursor()
        for term in query_terms:
            term_row = cursor.execute("SELECT idf FROM terms WHERE term = ?", (term,)).fetchone()
            if term_row is None:
                continue
            idf = float(term_row[0])
            rows = cursor.execute(
                """
                SELECT p.doc_idx, p.tf, d.token_count
                FROM postings p
                JOIN docs d ON d.doc_idx = p.doc_idx
                WHERE p.term = ?
                """,
                (term,),
            ).fetchall()
            for doc_idx, tf, token_count in rows:
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (token_count / max(self.avgdl, 1.0)))
                score = idf * ((tf * (self.k1 + 1.0)) / denominator)
                scores[int(doc_idx)] = scores.get(int(doc_idx), 0.0) + score

        return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]

    def dense_search(self, query: str, *, top_k: int = 10) -> list[tuple[int, float]]:
        query_vector = self.embedder.encode_queries([query])[0]
        scores = np.asarray(self.vectors @ query_vector, dtype=np.float32)
        if scores.size == 0:
            return []
        effective_top_k = min(top_k, scores.size)
        top_indices = np.argpartition(scores, -effective_top_k)[-effective_top_k:]
        ordered = top_indices[np.argsort(scores[top_indices])[::-1]]
        return [(int(index), float(scores[index])) for index in ordered]

    def vector_search(self, query: str, *, top_k: int = 10) -> list[dict]:
        hits = self.dense_search(query, top_k=top_k)
        return self._format_hits(hits, score_key="vector_score")

    def bm25_search(self, query: str, *, top_k: int = 10) -> list[dict]:
        hits = self.lexical_search(query, top_k=top_k)
        return self._format_hits(hits, score_key="bm25_score")

    def hybrid_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_pool: int | None = None,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> list[dict]:
        pool = max(top_k, candidate_pool or top_k * 4)
        dense_hits = self.dense_search(query, top_k=pool)
        lexical_hits = self.lexical_search(query, top_k=pool)
        if not dense_hits and not lexical_hits:
            return []

        dense_scores = {doc_idx: score for doc_idx, score in dense_hits}
        lexical_scores = {doc_idx: score for doc_idx, score in lexical_hits}
        fused_hits = reciprocal_rank_fusion(
            [[doc_idx for doc_idx, _ in dense_hits], [doc_idx for doc_idx, _ in lexical_hits]],
            rrf_k=rrf_k,
        )[:top_k]

        extra_fields = {
            doc_idx: {
                "vector_score": dense_scores.get(doc_idx, 0.0),
                "bm25_score": lexical_scores.get(doc_idx, 0.0),
            }
            for doc_idx, _ in fused_hits
        }
        return self._format_hits(fused_hits, score_key="rrf_score", extra_fields=extra_fields)

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        *,
        top_k: int | None = None,
        reranker_model: str | None = None,
        reranker_url: str | None = None,
        api_key: str | None = None,
    ) -> list[dict]:
        if not candidates:
            return []

        effective_top_k = top_k or len(candidates)
        api_key = api_key if api_key is not None else os.getenv("SILICONFLOW_API_KEY")
        if not api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is required for hybrid_rerank mode.")

        response = requests.post(
            reranker_url or os.getenv("SILICONFLOW_RERANKER_URL") or DEFAULT_RERANKER_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": reranker_model or os.getenv("SILICONFLOW_RERANKER_MODEL") or DEFAULT_RERANKER_MODEL,
                "query": query,
                "documents": [self._chunk_document(candidate) for candidate in candidates],
                "top_n": len(candidates),
                "return_documents": False,
            },
            timeout=90,
        )
        response.raise_for_status()

        reranked: list[dict] = []
        for item in response.json().get("results", []):
            index = int(item["index"])
            row = dict(candidates[index])
            row["rerank_score"] = float(item["relevance_score"])
            reranked.append(row)
        return reranked[:effective_top_k] or candidates[:effective_top_k]

    def hybrid_rerank_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_pool: int | None = None,
        rrf_k: int = DEFAULT_RRF_K,
        reranker_model: str | None = None,
        reranker_url: str | None = None,
        api_key: str | None = None,
    ) -> list[dict]:
        pool = max(top_k, candidate_pool or top_k * 4)
        candidates = self.hybrid_search(query, top_k=pool, candidate_pool=pool, rrf_k=rrf_k)
        return self.rerank(
            query,
            candidates,
            top_k=top_k,
            reranker_model=reranker_model,
            reranker_url=reranker_url,
            api_key=api_key,
        )

    def search(
        self,
        query: str,
        *,
        mode: RetrievalMode = "hybrid",
        top_k: int = 10,
        candidate_pool: int | None = None,
        rrf_k: int = DEFAULT_RRF_K,
        reranker_model: str | None = None,
        reranker_url: str | None = None,
        api_key: str | None = None,
    ) -> list[dict]:
        if mode == "vector":
            return self.vector_search(query, top_k=top_k)
        if mode == "bm25":
            return self.bm25_search(query, top_k=top_k)
        if mode == "hybrid":
            return self.hybrid_search(query, top_k=top_k, candidate_pool=candidate_pool, rrf_k=rrf_k)
        if mode == "hybrid_rerank":
            return self.hybrid_rerank_search(
                query,
                top_k=top_k,
                candidate_pool=candidate_pool,
                rrf_k=rrf_k,
                reranker_model=reranker_model,
                reranker_url=reranker_url,
                api_key=api_key,
            )
        raise ValueError(f"Chế độ truy hồi không hỗ trợ: {mode}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Truy vấn index hybrid local.")
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--mode",
        choices=RETRIEVAL_MODES,
        default="hybrid",
        help="vector: ngữ nghĩa; bm25: từ khoá; hybrid: vector+BM25 bằng RRF; hybrid_rerank: hybrid + rerank.",
    )
    parser.add_argument("--candidate-pool", type=int, help="Số candidate trước khi fusion/rerank (mặc định: top_k * 4).")
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)
    parser.add_argument("--reranker-model", default=os.getenv("SILICONFLOW_RERANKER_MODEL", DEFAULT_RERANKER_MODEL))
    parser.add_argument("--reranker-url", default=os.getenv("SILICONFLOW_RERANKER_URL", DEFAULT_RERANKER_URL))
    return parser.parse_args()


def main() -> None:
    configure_utf8_stdio()
    load_project_env()
    _self_check_rrf()
    args = parse_args()
    index = HybridIndex(args.index_dir)
    try:
        results = index.search(
            args.query,
            mode=args.mode,
            top_k=args.top_k,
            candidate_pool=args.candidate_pool,
            rrf_k=args.rrf_k,
            reranker_model=args.reranker_model,
            reranker_url=args.reranker_url,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        index.close()


if __name__ == "__main__":
    main()
