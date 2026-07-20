from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import chromadb
except ImportError as exc:  # pragma: no cover - dependency guard
    chromadb = None
    CHROMADB_IMPORT_ERROR = exc
else:
    CHROMADB_IMPORT_ERROR = None


@dataclass(slots=True)
class ChromaConnectionConfig:
    mode: str
    collection_name: str
    persist_path: Path
    tenant: str
    database: str
    http_host: str
    http_port: int
    http_ssl: bool
    http_headers: dict[str, str] | None
    cloud_api_key: str | None
    cloud_host: str
    cloud_port: int
    cloud_ssl: bool


def require_chromadb() -> Any:
    if chromadb is None:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "Môi trường hiện tại chưa cài chromadb. "
            "Hãy cài bằng `.venv\\Scripts\\python -m pip install chromadb`."
        ) from CHROMADB_IMPORT_ERROR
    return chromadb


def build_chroma_client(config: ChromaConnectionConfig) -> Any:
    chroma_module = require_chromadb()

    if config.mode == "local":
        config.persist_path.mkdir(parents=True, exist_ok=True)
        return chroma_module.PersistentClient(
            path=str(config.persist_path),
            tenant=config.tenant,
            database=config.database,
        )

    if config.mode == "http":
        return chroma_module.HttpClient(
            host=config.http_host,
            port=config.http_port,
            ssl=config.http_ssl,
            headers=config.http_headers,
            tenant=config.tenant,
            database=config.database,
        )

    if config.mode == "cloud":
        if not config.cloud_api_key:
            raise RuntimeError("Thiếu WEBAPP_CHROMA_CLOUD_API_KEY hoặc CHROMA_API_KEY cho chế độ cloud.")
        return chroma_module.CloudClient(
            tenant=config.tenant,
            database=config.database,
            api_key=config.cloud_api_key,
            cloud_host=config.cloud_host,
            cloud_port=config.cloud_port,
            enable_ssl=config.cloud_ssl,
        )

    raise ValueError(f"Chế độ Chroma không được hỗ trợ: {config.mode}")


def get_collection(client: Any, collection_name: str) -> Any:
    return client.get_collection(name=collection_name, embedding_function=None)


def parse_query_results(payload: dict[str, Any], *, distance_space: str) -> list[dict[str, Any]]:
    ids = payload.get("ids") or [[]]
    documents = payload.get("documents") or [[]]
    metadatas = payload.get("metadatas") or [[]]
    distances = payload.get("distances") or [[]]

    results: list[dict[str, Any]] = []
    for chunk_id, document, metadata, distance in zip(ids[0], documents[0], metadatas[0], distances[0]):
        numeric_distance = float(distance)
        score = 1.0 - numeric_distance if distance_space == "cosine" else -numeric_distance
        results.append(
            {
                "chunk_id": chunk_id,
                "distance": numeric_distance,
                "score": score,
                "document": document,
                "metadata": metadata,
            }
        )
    return results
