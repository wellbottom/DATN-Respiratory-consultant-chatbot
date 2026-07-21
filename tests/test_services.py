import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from scripts.RAG.retriever import HybridIndex
from web_app.backend import services
from web_app.backend.services import RetrievalEngine, SectionBundle, source_section_payload


class FakeCollection:
    def __init__(self) -> None:
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ids": [["a", "b"]],
            "documents": [["dense a", "dense b"]],
            "metadatas": [[{"corpus": "local_rag"}, {"corpus": "local_rag"}]],
            "distances": [[0.1, 0.2]],
        }


class RetrievalEngineTests(unittest.TestCase):
    def test_bm25_connection_works_from_fastapi_worker_thread(self) -> None:
        index = HybridIndex(Path("data/indexes/local_rag"))
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                results = executor.submit(index.lexical_search, "hen suyễn", top_k=3).result()
        finally:
            index.close()

        self.assertTrue(results)

    def test_routing_engine_is_removed(self) -> None:
        self.assertFalse(hasattr(services, "SplitCorpusRetrievalEngine"))

    def test_search_fuses_chroma_and_bm25_without_routing_filter(self) -> None:
        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine.settings = SimpleNamespace(query_top_k_per_corpus=2, rerank_candidate_limit=3)
        engine.collection_name = "local_rag"
        engine.knowledge_base = "general_medical"
        engine.distance_space = "cosine"
        engine.legacy_flat_chunks = False
        engine.embedder = SimpleNamespace(encode_queries=lambda _: [[1.0, 0.0]])
        engine.collection = FakeCollection()
        engine.hybrid_index = SimpleNamespace(
            chunks=[
                {"chunk_id": "b", "content": "lexical b", "corpus": "local_rag"},
                {"chunk_id": "c", "content": "lexical c", "corpus": "local_rag"},
            ],
            lexical_search=lambda query, top_k: [(0, 9.0), (1, 8.0)],
        )

        plan, results = engine.search("hen suyễn")

        self.assertEqual(plan.collection_name, "local_rag")
        self.assertEqual([item.chunk_id for item in results], ["b", "a", "c"])
        self.assertAlmostEqual(results[0].bm25_score, 9.0)
        self.assertAlmostEqual(results[0].vector_score, 0.8)
        self.assertGreater(results[0].rrf_score, results[1].rrf_score)
        self.assertNotIn("where", engine.collection.calls[0])

    def test_search_uses_chroma_without_local_hybrid_index(self) -> None:
        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine.settings = SimpleNamespace(rerank_candidate_limit=2)
        engine.collection_name = "local_rag"
        engine.knowledge_base = "general_medical"
        engine.distance_space = "cosine"
        engine.embedder = SimpleNamespace(encode_queries=lambda _: [[1.0, 0.0]])
        engine.collection = FakeCollection()
        engine.hybrid_index = None

        plan, results = engine.search("hen suyễn")

        self.assertEqual(plan.reasons, ["Vector retrieval from Chroma collection local_rag."])
        self.assertEqual([item.chunk_id for item in results], ["a", "b"])
        self.assertEqual([item.rrf_score for item in results], [0.0, 0.0])

    def test_source_payload_keeps_chunk_content(self) -> None:
        payload = source_section_payload(
            SectionBundle(
                section_id="s1",
                corpus="local_rag",
                title="data/markdown/source.md",
                h2=None,
                h3=None,
                section_type="nội dung",
                source_path="data/markdown/source.md",
                source_url=None,
                source_url_kind=None,
                rerank_score=0.1,
                vector_score=0.2,
                vector_distance=0.8,
                chunks=[
                    {
                        "chunk_id": "c1",
                        "candidate_chunk_index": 1,
                        "candidate_chunk_total": 1,
                        "content": "Nội dung chunk cần hiện trong popup.",
                    }
                ],
                text="Nội dung chunk cần hiện trong popup.",
            )
        )

        self.assertEqual(payload["chunks"][0]["content"], "Nội dung chunk cần hiện trong popup.")
        self.assertEqual(payload["vector_distance"], 0.8)


if __name__ == "__main__":
    unittest.main()
