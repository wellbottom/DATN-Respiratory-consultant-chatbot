from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from tqdm.auto import tqdm

from .common import configure_utf8_stdio, iter_jsonl, load_project_env, stable_hash
from .embedding import BaseEmbedder, build_embedder
from .indexing import build_dense_text, normalize_chunk_records

try:
    import chromadb
except ImportError as exc:  # pragma: no cover - dependency guard
    chromadb = None
    CHROMADB_IMPORT_ERROR = exc
else:
    CHROMADB_IMPORT_ERROR = None


DEFAULT_CHUNKS_PATH = Path("data/chunks/local_rag.chunks.jsonl")
DEFAULT_LOCAL_PERSIST_PATH = Path("web_app/storage/chroma")
DEFAULT_MANIFEST_DIR = Path("data/chroma_manifests")
DEFAULT_COLLECTION_NAME = "local_rag"
COLLECTION_METADATA_FIELDS = (
    "type",
    "source_file",
)


@dataclass(slots=True)
class ChromaIndexConfig:
    mode: str = "local"
    collection_name: str = DEFAULT_COLLECTION_NAME
    persist_path: str = DEFAULT_LOCAL_PERSIST_PATH.as_posix()
    tenant: str | None = None
    database: str | None = None
    api_key_env: str = "CHROMA_API_KEY"
    cloud_host: str = "api.trychroma.com"
    cloud_port: int = 443
    enable_ssl: bool = True
    distance_space: str = "cosine"
    embedding_backend: str = "siliconflow"
    embedding_dimension: int | None = None
    embedding_model_name: str | None = None
    embedding_batch_size: int = 128
    upsert_batch_size: int = 256


def require_chromadb() -> Any:
    if chromadb is None:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "Chưa cài chromadb trong môi trường hiện tại. "
            "Cài bằng `.venv\\Scripts\\python -m pip install chromadb`."
        ) from CHROMADB_IMPORT_ERROR
    return chromadb


def sanitize_metadata_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        items = [sanitize_metadata_value(item) for item in value]
        items = [item for item in items if item is not None]
        if not items:
            return None
        if all(isinstance(item, bool) for item in items):
            return items
        if all(isinstance(item, int) and not isinstance(item, bool) for item in items):
            return items
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in items):
            return [float(item) for item in items]
        if all(isinstance(item, str) for item in items):
            return items
        return [str(item) for item in items]
    return str(value)


def build_chunk_metadata(chunk: dict) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field in COLLECTION_METADATA_FIELDS:
        value = sanitize_metadata_value(chunk.get(field))
        if value is not None:
            metadata[field] = value
    return metadata


def build_client(config: ChromaIndexConfig) -> Any:
    chroma_module = require_chromadb()
    load_project_env()
    if config.mode == "local":
        persist_path = Path(config.persist_path)
        persist_path.mkdir(parents=True, exist_ok=True)
        return chroma_module.PersistentClient(path=str(persist_path))
    if config.mode == "cloud":
        import os

        api_key = os.getenv(config.api_key_env)
        return chroma_module.CloudClient(
            tenant=config.tenant,
            database=config.database,
            api_key=api_key,
            cloud_host=config.cloud_host,
            cloud_port=config.cloud_port,
            enable_ssl=config.enable_ssl,
        )
    raise ValueError(f"Chế độ Chroma không hỗ trợ: {config.mode}")


def resolve_source_manifest_path(chunks_path: Path, vectors_path: Path | None) -> Path | None:
    candidates: list[Path] = []
    if vectors_path is not None:
        candidates.append(vectors_path.with_name("manifest.json"))
    candidates.append(chunks_path.with_name("manifest.json"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_source_manifest(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_embedder(
    config: ChromaIndexConfig,
    *,
    source_manifest: dict | None = None,
    collection_metadata: dict[str, Any] | None = None,
) -> BaseEmbedder:
    embedding_block: dict[str, Any] = {}
    if source_manifest and isinstance(source_manifest.get("dense"), dict):
        dense = source_manifest["dense"]
        if isinstance(dense.get("embedding"), dict):
            embedding_block.update(dense["embedding"])
    if collection_metadata:
        for key in (
            "embedding_backend",
            "embedding_dimension",
            "embedding_model_name",
            "embedding_use_bigrams",
            "embedding_endpoint",
            "embedding_api_key_env",
            "embedding_timeout_seconds",
            "embedding_max_batch_size",
        ):
            if collection_metadata.get(key) is not None:
                embedding_block[key] = collection_metadata[key]

    backend = str(embedding_block.get("embedding_backend") or embedding_block.get("backend") or config.embedding_backend)
    dimension_value = embedding_block.get("embedding_dimension", embedding_block.get("dimension", config.embedding_dimension))
    dimension = int(dimension_value) if dimension_value is not None else None
    model_name = embedding_block.get("embedding_model_name", embedding_block.get("model_name", config.embedding_model_name))
    use_bigrams = embedding_block.get("embedding_use_bigrams", embedding_block.get("use_bigrams"))
    endpoint = embedding_block.get("embedding_endpoint", embedding_block.get("endpoint"))
    api_key_env = str(embedding_block.get("embedding_api_key_env", embedding_block.get("api_key_env", "SILICONFLOW_API_KEY")))
    timeout_value = embedding_block.get("embedding_timeout_seconds", embedding_block.get("timeout_seconds"))
    timeout_seconds = float(timeout_value) if timeout_value is not None else None
    max_batch_value = embedding_block.get("embedding_max_batch_size", embedding_block.get("max_batch_size"))
    max_batch_size = int(max_batch_value) if max_batch_value is not None else None

    return build_embedder(
        backend,
        dimension=dimension,
        model_name=model_name,
        use_bigrams=bool(use_bigrams) if use_bigrams is not None else None,
        endpoint=endpoint,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
        max_batch_size=max_batch_size,
    )


def collection_runtime_metadata(
    config: ChromaIndexConfig,
    *,
    chunks_path: Path,
    vectors_path: Path | None,
    embedder: BaseEmbedder,
    source_manifest: dict | None,
    chunk_count: int,
) -> dict[str, Any]:
    embedding_metadata = embedder.metadata()
    metadata = {
        "dataset": "vinmec",
        "index_backend": "chromadb",
        "mode": config.mode,
        "distance_space": config.distance_space,
        "chunks_path": chunks_path.resolve().as_posix(),
        "chunk_count": int(chunk_count),
        "vectors_path": vectors_path.resolve().as_posix() if vectors_path is not None else "",
        "embedding_backend": embedding_metadata.get("backend"),
        "embedding_dimension": int(embedding_metadata["dimension"]) if embedding_metadata.get("dimension") is not None else None,
        "embedding_model_name": embedding_metadata.get("model_name"),
        "embedding_endpoint": embedding_metadata.get("endpoint"),
        "embedding_api_key_env": embedding_metadata.get("api_key_env"),
        "embedding_timeout_seconds": embedding_metadata.get("timeout_seconds"),
        "embedding_max_batch_size": embedding_metadata.get("max_batch_size"),
        "embedding_use_bigrams": embedding_metadata.get("use_bigrams"),
        "source_manifest_path": source_manifest.get("_manifest_path") if source_manifest else "",
    }
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized = sanitize_metadata_value(value)
        if normalized is not None:
            sanitized[key] = normalized
    return sanitized


def manifest_file_name(collection_name: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "_", collection_name.casefold()).strip("._-")
    return f"{slug or 'collection'}.json"


def write_manifest(manifest_path: Path, payload: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_chunk_batches(chunks_path: Path, batch_size: int, *, max_records: int | None = None) -> Iterable[list[dict]]:
    batch: list[dict] = []
    seen = 0
    for row in iter_jsonl(chunks_path):
        if max_records is not None and seen >= max_records:
            break
        batch.append(row)
        seen += 1
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def build_documents(chunks: Sequence[dict]) -> list[str]:
    return [str(chunk.get("text") or build_dense_text(chunk)) for chunk in chunks]


def build_embedding_texts(chunks: Sequence[dict]) -> list[str]:
    return [build_dense_text(chunk) for chunk in chunks]


def iter_normalized_chunk_batches(
    chunks_path: Path,
    batch_size: int,
    *,
    max_records: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    cursor = 0
    for batch in iter_chunk_batches(chunks_path, batch_size, max_records=max_records):
        normalized = normalize_chunk_records(batch)
        for chunk in normalized:
            chunk["chunk_index"] = cursor
            cursor += 1
        yield normalized


def prepare_collection(client: Any, config: ChromaIndexConfig, *, metadata: dict[str, Any]) -> Any:
    return client.get_or_create_collection(
        name=config.collection_name,
        metadata=metadata,
        configuration={"hnsw": {"space": config.distance_space}},
        embedding_function=None,
    )


def maybe_delete_collection(client: Any, collection_name: str) -> None:
    try:
        client.delete_collection(collection_name)
    except Exception as exc:  # pragma: no cover - client-specific error types
        lowered = str(exc).casefold()
        if "not found" in lowered or "does not exist" in lowered:
            return
        raise


def sync_collection(
    chunks_path: Path,
    *,
    config: ChromaIndexConfig,
    vectors_path: Path | None = None,
    source_manifest_path: Path | None = None,
    recreate: bool = False,
    manifest_output: Path | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file chunks: {chunks_path}")
    if vectors_path is not None and not vectors_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file vectors: {vectors_path}")

    detected_manifest_path = source_manifest_path or resolve_source_manifest_path(chunks_path, vectors_path)
    source_manifest = load_source_manifest(detected_manifest_path)
    if source_manifest is not None:
        source_manifest["_manifest_path"] = detected_manifest_path.resolve().as_posix()

    embedder = resolve_embedder(config, source_manifest=source_manifest)
    client = build_client(config)
    if recreate:
        maybe_delete_collection(client, config.collection_name)

    vector_rows = np.load(vectors_path, mmap_mode="r") if vectors_path is not None else None
    if vector_rows is not None and len(vector_rows.shape) != 2:
        raise ValueError(f"Embedding phải là mảng 2D, hiện nhận shape {vector_rows.shape}.")

    chunk_total = int(vector_rows.shape[0]) if vector_rows is not None else sum(1 for _ in iter_jsonl(chunks_path))
    if max_records is not None:
        chunk_total = min(chunk_total, max(0, int(max_records)))
    collection_metadata = collection_runtime_metadata(
        config,
        chunks_path=chunks_path,
        vectors_path=vectors_path,
        embedder=embedder,
        source_manifest=source_manifest,
        chunk_count=chunk_total,
    )
    collection = prepare_collection(client, config, metadata=collection_metadata)

    requested_batch_size = max(1, int(config.upsert_batch_size))
    try:
        max_batch_size = int(client.get_max_batch_size())
    except Exception:  # pragma: no cover - client-specific capabilities
        max_batch_size = requested_batch_size
    effective_batch_size = max(1, min(requested_batch_size, max_batch_size))

    cursor = 0
    batches_processed = 0
    total_batches = math.ceil(chunk_total / effective_batch_size) if chunk_total else 0
    for batch in tqdm(
        iter_normalized_chunk_batches(chunks_path, effective_batch_size, max_records=max_records),
        total=total_batches,
        desc="Upserting to Chroma",
        unit="batch",
    ):
        ids = [str(chunk["chunk_id"]) for chunk in batch]
        documents = build_documents(batch)
        metadatas = [build_chunk_metadata(chunk) for chunk in batch]
        if vector_rows is not None:
            batch_vectors = np.asarray(vector_rows[cursor : cursor + len(batch)], dtype=np.float32).tolist()
        else:
            batch_vectors = embedder.encode(build_embedding_texts(batch), batch_size=config.embedding_batch_size).tolist()
        collection.upsert(
            ids=ids,
            embeddings=batch_vectors,
            documents=documents,
            metadatas=metadatas,
        )
        cursor += len(batch)
        batches_processed += 1

    if vector_rows is not None and cursor != chunk_total:
        raise ValueError(
            f"Số chunks ({cursor}) không khớp số vectors cần import ({chunk_total})."
        )

    collection.modify(metadata=collection_metadata)
    runtime_manifest = {
        "index_id": stable_hash(
            config.collection_name,
            chunks_path.resolve().as_posix(),
            json.dumps(asdict(config), sort_keys=True),
            length=20,
        ),
        "index_backend": "chromadb",
        "collection_name": config.collection_name,
        "mode": config.mode,
        "persist_path": Path(config.persist_path).resolve().as_posix() if config.mode == "local" else None,
        "chunks_path": chunks_path.resolve().as_posix(),
        "vectors_path": vectors_path.resolve().as_posix() if vectors_path is not None else None,
        "source_manifest_path": detected_manifest_path.resolve().as_posix() if detected_manifest_path is not None else None,
        "chunk_count": chunk_total,
        "collection_count": int(collection.count()),
        "effective_batch_size": effective_batch_size,
        "batches_processed": batches_processed,
        "embedding": embedder.metadata(),
        "collection_metadata": collection_metadata,
        "config": asdict(config),
    }
    if manifest_output is not None:
        write_manifest(manifest_output, runtime_manifest)
        runtime_manifest["manifest_path"] = manifest_output.resolve().as_posix()
    return runtime_manifest


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


def query_collection(
    query: str,
    *,
    config: ChromaIndexConfig,
    top_k: int,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("Query không được rỗng.")

    client = build_client(config)
    collection = get_collection(client, config.collection_name)
    collection_metadata = dict(getattr(collection, "metadata", {}) or {})
    distance_space = str(collection_metadata.get("distance_space") or config.distance_space)
    embedder = resolve_embedder(config, collection_metadata=collection_metadata)
    query_vector = embedder.encode_queries([query], batch_size=config.embedding_batch_size)[0].tolist()
    response = collection.query(
        query_embeddings=[query_vector],
        n_results=max(1, int(top_k)),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return {
        "collection_name": config.collection_name,
        "mode": config.mode,
        "query": query,
        "top_k": max(1, int(top_k)),
        "where": where,
        "distance_space": distance_space,
        "embedding": embedder.metadata(),
        "results": parse_query_results(response, distance_space=distance_space),
    }


def parse_where_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("--where-json phải decode ra JSON object.")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build và truy vấn collection ChromaDB cho dữ liệu RAG.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Upsert chunks vào collection Chroma.")
    build_parser.add_argument("--mode", choices=["local", "cloud"], default="local")
    build_parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME)
    build_parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    build_parser.add_argument("--vectors", type=Path, help="File embeddings .npy có sẵn để import.")
    build_parser.add_argument("--source-manifest", type=Path, help="File manifest.json dùng để lấy cấu hình embedding.")
    build_parser.add_argument("--persist-path", type=Path, default=DEFAULT_LOCAL_PERSIST_PATH)
    build_parser.add_argument("--tenant")
    build_parser.add_argument("--database")
    build_parser.add_argument("--api-key-env", default="CHROMA_API_KEY")
    build_parser.add_argument("--cloud-host", default="api.trychroma.com")
    build_parser.add_argument("--cloud-port", type=int, default=443)
    build_parser.add_argument("--disable-ssl", action="store_true")
    build_parser.add_argument("--distance-space", default="cosine")
    build_parser.add_argument("--embedding-backend", default="siliconflow")
    build_parser.add_argument("--embedding-dimension", type=int)
    build_parser.add_argument("--embedding-model-name")
    build_parser.add_argument("--embedding-batch-size", type=int, default=128)
    build_parser.add_argument("--upsert-batch-size", type=int, default=256)
    build_parser.add_argument("--recreate", action="store_true", help="Xoá collection đích trước khi build lại.")
    build_parser.add_argument("--max-records", type=int, help="Giới hạn số record để build thử.")
    build_parser.add_argument(
        "--manifest-output",
        type=Path,
        help="Nơi ghi manifest JSON. Mặc định là data/chroma_manifests/<collection>.json.",
    )

    query_parser = subparsers.add_parser("query", help="Truy vấn collection Chroma có sẵn.")
    query_parser.add_argument("--mode", choices=["local", "cloud"], default="local")
    query_parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME)
    query_parser.add_argument("--persist-path", type=Path, default=DEFAULT_LOCAL_PERSIST_PATH)
    query_parser.add_argument("--tenant")
    query_parser.add_argument("--database")
    query_parser.add_argument("--api-key-env", default="CHROMA_API_KEY")
    query_parser.add_argument("--cloud-host", default="api.trychroma.com")
    query_parser.add_argument("--cloud-port", type=int, default=443)
    query_parser.add_argument("--disable-ssl", action="store_true")
    query_parser.add_argument("--query", required=True)
    query_parser.add_argument("--top-k", type=int, default=5)
    query_parser.add_argument("--where-json", help="Filter metadata dạng JSON truyền vào where của Chroma.")
    query_parser.add_argument("--embedding-backend", default="siliconflow")
    query_parser.add_argument("--embedding-dimension", type=int)
    query_parser.add_argument("--embedding-model-name")
    query_parser.add_argument("--embedding-batch-size", type=int, default=128)
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> ChromaIndexConfig:
    return ChromaIndexConfig(
        mode=args.mode,
        collection_name=args.collection,
        persist_path=Path(args.persist_path).as_posix(),
        tenant=args.tenant,
        database=args.database,
        api_key_env=args.api_key_env,
        cloud_host=args.cloud_host,
        cloud_port=args.cloud_port,
        enable_ssl=not getattr(args, "disable_ssl", False),
        distance_space=getattr(args, "distance_space", "cosine"),
        embedding_backend=args.embedding_backend,
        embedding_dimension=args.embedding_dimension,
        embedding_model_name=args.embedding_model_name,
        embedding_batch_size=args.embedding_batch_size,
        upsert_batch_size=getattr(args, "upsert_batch_size", 256),
    )


def default_manifest_output(collection_name: str) -> Path:
    return DEFAULT_MANIFEST_DIR / manifest_file_name(collection_name)


def main() -> None:
    configure_utf8_stdio()
    load_project_env()
    args = parse_args()
    config = config_from_args(args)

    if args.command == "build":
        manifest_output = args.manifest_output or default_manifest_output(args.collection)
        manifest = sync_collection(
            args.chunks,
            config=config,
            vectors_path=args.vectors,
            source_manifest_path=args.source_manifest,
            recreate=args.recreate,
            manifest_output=manifest_output,
            max_records=args.max_records,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    results = query_collection(
        args.query,
        config=config,
        top_k=args.top_k,
        where=parse_where_json(args.where_json),
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
