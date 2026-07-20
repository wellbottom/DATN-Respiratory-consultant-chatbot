# Webapp Local RAG Hybrid Search Design

## Goal

Make the webapp search only the `local_rag` knowledge base using Chroma HNSW dense retrieval plus the existing local BM25 index, fuse both rankings with the existing reciprocal-rank-fusion implementation, and remove retrieval routing.

## Architecture

`RetrievalEngine` remains the webapp retrieval boundary. For every query it retrieves dense candidates from the configured `local_rag` Chroma collection and lexical candidates from `data/indexes/local_rag/lexical.sqlite3`. Both branches identify documents by the chunk IDs stored in `data/indexes/local_rag/chunks.jsonl`. Their ranked chunk-ID lists are fused by `scripts.RAG.retriever.reciprocal_rank_fusion` with `k=60`, then limited to the existing rerank candidate limit and passed to the existing SiliconFlow reranker.

The webapp must not route queries to child, diseases, medication, or body-part retrieval engines. It must not filter retrieval by inferred corpus or intent. Query contextualization, reranking, section expansion, context construction, source payloads, and answer generation remain unchanged.

## Data Flow

1. Contextualize the user query as today.
2. Query the `local_rag` Chroma collection with its dense embedding and HNSW index.
3. Query the existing local BM25 index with the same text.
4. Convert both result lists to the same stable `chunk_id` identity.
5. Fuse ranks with reciprocal rank fusion; do not combine raw vector and BM25 scores.
6. Preserve `vector_score`, `vector_distance`, `bm25_score`, and `rrf_score` on candidates for diagnostics and source payloads.
7. Rerank the fused candidate pool with the existing reranker.
8. Expand sections and generate the answer through the existing pipeline.

## Configuration and Startup

The active collection is `local_rag`. The backend reads BM25 artifacts from `WEBAPP_HYBRID_INDEX_DIR`, defaulting to `data/indexes/local_rag` relative to the repository root. Production deploys must copy this directory into the backend image or mount it as a read-only volume. No new dependency or second BM25 implementation is introduced.

The webapp validates the required local artifacts (`manifest.json`, `chunks.jsonl`, and `lexical.sqlite3`) when constructing retrieval. Missing or incompatible artifacts cause a clear startup error; the application must not silently degrade to vector-only retrieval.

## Routing Removal

Remove `SplitCorpusRetrievalEngine`, specialized retrieval-engine construction, route-term construction, and `_select_retrieval_engine`. `MedicalRAGService.chat` calls the single `RetrievalEngine` directly. Existing settings may remain temporarily if removing them would expand the change into unrelated environment compatibility work, but they must no longer affect retrieval.

## Error Handling

BM25 initialization or query failures are retrieval failures and are surfaced rather than hidden. Existing reranker failure behavior remains: return the fused candidates and record reranker fallback diagnostics.

## Testing

Tests use small temporary local index artifacts and a fake Chroma collection. They verify that:

- a chunk ranked by both branches receives the combined RRF score and is ordered accordingly;
- raw BM25 and vector scores are preserved;
- retrieval searches the complete `local_rag` collection without corpus or intent routing filters;
- the chat pipeline uses the single retrieval engine;
- missing BM25 artifacts produce a clear initialization error;
- existing authentication and source-payload tests remain green.

## Non-goals

- Rebuilding or tuning embeddings, HNSW, BM25 parameters, or the reranker.
- Adding weighted score fusion.
- Supporting hybrid retrieval across specialized collections.
- Adding a vector-only fallback.
