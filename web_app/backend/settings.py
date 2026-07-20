from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL

from .env import load_local_env


def getenv_any(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def getenv_bool(*names: str, default: bool) -> bool:
    value = getenv_any(*names)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def getenv_int(*names: str, default: int) -> int:
    value = getenv_any(*names)
    return int(value) if value is not None else default


def getenv_float(*names: str, default: float) -> float:
    value = getenv_any(*names)
    return float(value) if value is not None else default


def getenv_path(*names: str) -> Path | None:
    value = getenv_any(*names)
    if not value:
        return None
    return Path(value).expanduser()


def getenv_json_object(*names: str) -> dict[str, str] | None:
    raw = getenv_any(*names)
    if not raw:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Bien {names[0]} phai la mot doi tuong JSON.")
    return {str(key): str(value) for key, value in parsed.items()}


def getenv_list(*names: str) -> tuple[str, ...]:
    raw = getenv_any(*names)
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def build_llm_providers() -> tuple[dict[str, str], ...]:
    providers: list[dict[str, str]] = []
    llm_key = getenv_any("LLM_API_KEY", "GROQ_API_KEY")
    if llm_key:
        providers.append(
            {
                "name": getenv_any("LLM_PROVIDER_NAME", default="groq") or "groq",
                "endpoint": getenv_any(
                    "LLM_API_URL",
                    "LLM_ENDPOINT",
                    default="https://api.groq.com/openai/v1/chat/completions",
                )
                or "https://api.groq.com/openai/v1/chat/completions",
                "api_key": llm_key,
                "model": getenv_any("LLM_MODEL", default="openai/gpt-oss-120b") or "openai/gpt-oss-120b",
            }
        )
    return tuple(providers)


def normalize_database_url(raw_url: str) -> str:
    database_url = raw_url.strip()
    if database_url.startswith("postgres://"):
        return f"postgresql+psycopg://{database_url[len('postgres://') :]}"
    if database_url.startswith("postgresql://") and not database_url.startswith("postgresql+"):
        return f"postgresql+psycopg://{database_url[len('postgresql://') :]}"
    return database_url


def build_database_url(app_root: Path) -> tuple[str, Path]:
    database_path = (getenv_path("WEBAPP_DATABASE_PATH") or app_root / "storage" / "app.sqlite3").resolve()

    explicit_url = getenv_any("WEBAPP_DATABASE_URL", "DATABASE_URL")
    if explicit_url:
        return normalize_database_url(explicit_url), database_path

    host = getenv_any("WEBAPP_DATABASE_HOST", "SUPABASE_DB_HOST", "POSTGRES_HOST", "PGHOST")
    port_value = getenv_any("WEBAPP_DATABASE_PORT", "SUPABASE_DB_PORT", "POSTGRES_PORT", "PGPORT")
    user = getenv_any("WEBAPP_DATABASE_USER", "SUPABASE_DB_USER", "POSTGRES_USER", "PGUSER")
    password = getenv_any("WEBAPP_DATABASE_PASSWORD", "SUPABASE_DB_PASSWORD", "POSTGRES_PASSWORD", "PGPASSWORD")
    database_name = getenv_any("WEBAPP_DATABASE_NAME", "SUPABASE_DB_NAME", "POSTGRES_DB", "PGDATABASE")

    if any(value is not None for value in (host, port_value, user, password, database_name)):
        missing_fields = [
            field_name
            for field_name, field_value in (
                ("WEBAPP_DATABASE_HOST", host),
                ("WEBAPP_DATABASE_USER", user),
                ("WEBAPP_DATABASE_PASSWORD", password),
                ("WEBAPP_DATABASE_NAME", database_name),
            )
            if not field_value
        ]
        if missing_fields:
            raise RuntimeError("Missing database settings for Postgres/Supabase: " + ", ".join(missing_fields))

        port = int(port_value) if port_value is not None else 5432
        sslmode = getenv_any("WEBAPP_DATABASE_SSLMODE", "SUPABASE_DB_SSLMODE")
        if not sslmode and host and "supabase" in host.lower():
            sslmode = "require"

        query: dict[str, str] = {}
        if sslmode:
            query["sslmode"] = sslmode.strip()

        database_url = URL.create(
            "postgresql+psycopg",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database_name,
            query=query,
        )
        return database_url.render_as_string(hide_password=False), database_path

    return f"sqlite:///{database_path.as_posix()}", database_path


def has_local_chroma_data(path: Path) -> bool:
    return path.exists() and path.is_dir() and any(path.iterdir())


def has_local_chroma_collection(path: Path, collection_name: str) -> bool:
    if not has_local_chroma_data(path):
        return False

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(path))
        return any(collection.name == collection_name for collection in client.list_collections())
    except Exception:
        return False


def has_local_chroma_collections(path: Path, collection_names: tuple[str, ...]) -> bool:
    if not collection_names or not has_local_chroma_data(path):
        return False

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(path))
        existing_names = {collection.name for collection in client.list_collections()}
        return all(collection_name in existing_names for collection_name in collection_names)
    except Exception:
        return False


@dataclass(slots=True)
class AppSettings:
    app_name: str
    app_root: Path
    frontend_dir: Path
    frontend_dist_dir: Path
    database_url: str
    database_path: Path
    chroma_mode: str
    chroma_collection_name: str
    chroma_child_collection_name: str
    chroma_diseases_collection_name: str
    chroma_persist_path: Path
    chroma_tenant: str
    chroma_database: str
    chroma_http_host: str
    chroma_http_port: int
    chroma_http_ssl: bool
    chroma_http_headers: dict[str, str] | None
    chroma_cloud_api_key: str | None
    chroma_cloud_host: str
    chroma_cloud_port: int
    chroma_cloud_ssl: bool
    section_store_path: Path | None
    hybrid_index_dir: Path
    siliconflow_api_key: str
    embedding_model_name: str
    embedding_endpoint: str
    embedding_dimension: int
    embedding_batch_size: int
    embedding_max_batch_size: int
    embedding_timeout_seconds: float
    reranker_model: str
    reranker_url: str
    llm_model: str
    llm_providers: tuple[dict[str, str], ...]
    query_top_k_per_corpus: int
    fallback_top_k_per_corpus: int
    rerank_candidate_limit: int
    final_section_limit: int
    max_context_characters: int
    request_timeout_seconds: float
    clerk_publishable_key: str | None
    clerk_secret_key: str | None
    clerk_frontend_api_url: str | None
    clerk_jwt_key: str | None
    clerk_jwks_url: str | None
    clerk_allowed_origins: tuple[str, ...]


def load_settings() -> AppSettings:
    app_root = Path(__file__).resolve().parents[1]
    load_local_env(root=app_root)

    siliconflow_api_key = getenv_any("SILICONFLOW_API_KEY")
    if not siliconflow_api_key:
        raise RuntimeError("Thieu SILICONFLOW_API_KEY trong bien moi truong.")

    llm_providers = build_llm_providers()
    if not llm_providers:
        raise RuntimeError("Thiếu GROQ_API_KEY hoặc LLM_API_KEY trong biến môi trường.")

    chroma_mode = getenv_any("WEBAPP_CHROMA_MODE", default="local") or "local"
    chroma_mode = chroma_mode.strip().lower()
    if chroma_mode not in {"local", "http", "cloud"}:
        raise RuntimeError("WEBAPP_CHROMA_MODE phai la mot trong cac gia tri: local, http, cloud.")

    collection_name = getenv_any("WEBAPP_CHROMA_COLLECTION", "WEBAPP_VECTOR_COLLECTION", default="local_rag") or "local_rag"
    child_collection_name = (
        getenv_any("WEBAPP_CHROMA_CHILD_COLLECTION", "WEBAPP_CHILD_CHROMA_COLLECTION", default=collection_name)
        or collection_name
    )
    diseases_collection_name = (
        getenv_any(
            "WEBAPP_CHROMA_DISEASES_COLLECTION",
            "WEBAPP_DISEASES_CHROMA_COLLECTION",
            default=collection_name,
        )
        or collection_name
    )
    database_url, database_path = build_database_url(app_root)

    default_persist_candidates = [
        app_root / "storage" / "chroma",
    ]
    split_primary_collections = (child_collection_name, diseases_collection_name)
    default_persist_path = next(
        (path for path in default_persist_candidates if has_local_chroma_collections(path, split_primary_collections)),
        next(
            (path for path in default_persist_candidates if has_local_chroma_collection(path, collection_name)),
            next((path for path in default_persist_candidates if has_local_chroma_data(path)), default_persist_candidates[0]),
        ),
    )
    hybrid_index_dir = getenv_path("WEBAPP_HYBRID_INDEX_DIR") or app_root.parent / "data" / "indexes" / "local_rag"
    section_store_path = getenv_path("WEBAPP_SECTION_STORE_PATH") or hybrid_index_dir / "chunks.jsonl"

    return AppSettings(
        app_name="HealthyLung",
        app_root=app_root,
        frontend_dir=app_root / "frontend",
        frontend_dist_dir=(app_root / "frontend" / "dist").resolve(),
        database_url=database_url,
        database_path=database_path,
        chroma_mode=chroma_mode,
        chroma_collection_name=collection_name,
        chroma_child_collection_name=child_collection_name,
        chroma_diseases_collection_name=diseases_collection_name,
        chroma_persist_path=getenv_path("WEBAPP_CHROMA_PERSIST_PATH", "WEBAPP_VECTOR_PERSIST_PATH") or default_persist_path,
        chroma_tenant=getenv_any("WEBAPP_CHROMA_TENANT", default="default_tenant") or "default_tenant",
        chroma_database=getenv_any("WEBAPP_CHROMA_DATABASE", default="default_database") or "default_database",
        chroma_http_host=getenv_any("WEBAPP_CHROMA_HTTP_HOST", default="localhost") or "localhost",
        chroma_http_port=getenv_int("WEBAPP_CHROMA_HTTP_PORT", default=8000),
        chroma_http_ssl=getenv_bool("WEBAPP_CHROMA_HTTP_SSL", default=False),
        chroma_http_headers=getenv_json_object("WEBAPP_CHROMA_HTTP_HEADERS_JSON"),
        chroma_cloud_api_key=getenv_any("WEBAPP_CHROMA_CLOUD_API_KEY", "CHROMA_API_KEY"),
        chroma_cloud_host=getenv_any("WEBAPP_CHROMA_CLOUD_HOST", default="api.trychroma.com") or "api.trychroma.com",
        chroma_cloud_port=getenv_int("WEBAPP_CHROMA_CLOUD_PORT", default=443),
        chroma_cloud_ssl=getenv_bool("WEBAPP_CHROMA_CLOUD_SSL", default=True),
        section_store_path=section_store_path,
        hybrid_index_dir=hybrid_index_dir,
        siliconflow_api_key=siliconflow_api_key,
        embedding_model_name=getenv_any("WEBAPP_EMBEDDING_MODEL", "SILICONFLOW_EMBEDDING_MODEL", default="Qwen/Qwen3-Embedding-4B")
        or "Qwen/Qwen3-Embedding-4B",
        embedding_endpoint=getenv_any(
            "WEBAPP_EMBEDDING_ENDPOINT",
            "SILICONFLOW_EMBEDDINGS_URL",
            default="https://api.siliconflow.com/v1/embeddings",
        )
        or "https://api.siliconflow.com/v1/embeddings",
        embedding_dimension=getenv_int("WEBAPP_EMBEDDING_DIMENSION", "SILICONFLOW_EMBEDDING_DIMENSIONS", default=2560),
        embedding_batch_size=getenv_int("WEBAPP_EMBEDDING_BATCH_SIZE", default=128),
        embedding_max_batch_size=getenv_int("WEBAPP_EMBEDDING_MAX_BATCH_SIZE", "SILICONFLOW_MAX_BATCH_SIZE", default=32),
        embedding_timeout_seconds=getenv_float("WEBAPP_EMBEDDING_TIMEOUT_SECONDS", "SILICONFLOW_TIMEOUT_SECONDS", default=120.0),
        reranker_model=getenv_any("SILICONFLOW_RERANKER_MODEL", default="Qwen/Qwen3-Reranker-8B") or "Qwen/Qwen3-Reranker-8B",
        reranker_url=getenv_any("SILICONFLOW_RERANKER_URL", default="https://api.siliconflow.com/v1/rerank")
        or "https://api.siliconflow.com/v1/rerank",
        llm_model=getenv_any("LLM_MODEL", default="openai/gpt-oss-120b") or "openai/gpt-oss-120b",
        llm_providers=llm_providers,
        query_top_k_per_corpus=getenv_int("WEBAPP_QUERY_TOP_K_PER_CORPUS", default=10),
        fallback_top_k_per_corpus=getenv_int("WEBAPP_FALLBACK_TOP_K_PER_CORPUS", default=6),
        rerank_candidate_limit=getenv_int("WEBAPP_RERANK_CANDIDATE_LIMIT", default=20),
        final_section_limit=getenv_int("WEBAPP_FINAL_SECTION_LIMIT", default=5),
        max_context_characters=getenv_int("WEBAPP_MAX_CONTEXT_CHARACTERS", default=0),
        request_timeout_seconds=getenv_float("WEBAPP_REQUEST_TIMEOUT_SECONDS", default=90.0),
        clerk_publishable_key=getenv_any("CLERK_PUBLISHABLE_KEY", "VITE_CLERK_PUBLISHABLE_KEY"),
        clerk_secret_key=getenv_any("CLERK_SECRET_KEY"),
        clerk_frontend_api_url=getenv_any("CLERK_FRONTEND_API_URL"),
        clerk_jwt_key=getenv_any("CLERK_JWT_KEY"),
        clerk_jwks_url=getenv_any("CLERK_JWKS_URL"),
        clerk_allowed_origins=getenv_list("CLERK_ALLOWED_ORIGINS", "WEBAPP_ALLOWED_ORIGINS")
        or (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
            "http://127.0.0.1:5175",
            "http://localhost:5175",
            "http://127.0.0.1:8001",
            "http://localhost:8001",
            "http://127.0.0.1:8002",
            "http://localhost:8002",
            "http://127.0.0.1:8003",
            "http://localhost:8003",
            "http://127.0.0.1:8004",
            "http://localhost:8004",
        ),
    )
