from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.RAG import chunking, generator, indexing, retriever


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_dir = root / "docs"
        source_dir.mkdir()
        (source_dir / "sample.md").write_text(
            "# Tieu de\n\n## Tong quan\n\nNoi dung mau de tao chunk.",
            encoding="utf-8",
        )

        rows = chunking.build_document_chunks(source_dir / "sample.md", chunking.ChunkingConfig())
        assert rows and set(rows[0]) == {"text", "type", "source_file"}

        stats = chunking.build_chunk_file([source_dir], root / "chunks.jsonl", stats_path=root / "stats.json")
        assert "corpora" not in stats
        assert stats["documents"] == 1

    assert hasattr(retriever, "HybridIndex")
    assert not hasattr(indexing, "HybridIndex")
    assert hasattr(generator, "RequestLLMClient")

    class FakeResponse:
        status_code = 200
        text = ""
        reason = "OK"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "xin chào"}}]}

    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def post(self, endpoint: str, *, headers: dict, json: dict, timeout: float) -> FakeResponse:
            self.calls.append({"endpoint": endpoint, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    session = FakeSession()
    client = generator.RequestLLMClient(
        [{"name": "fake", "endpoint": "https://example.test/v1/chat/completions", "api_key": "key"}],
        model="model",
        session=session,
    )
    assert client.chat([{"role": "user", "content": "hello"}]) == "xin chào"
    assert session.calls[0]["headers"]["Authorization"] == "Bearer key"

    services_source = (ROOT / "web_app" / "backend" / "services.py").read_text(encoding="utf-8")
    assert "class " + "Cpab" + "ChatClient" not in services_source


if __name__ == "__main__":
    main()
