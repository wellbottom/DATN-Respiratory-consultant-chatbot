from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
from tqdm.auto import tqdm

from .common import configure_utf8_stdio, iter_jsonl, load_project_env, simple_word_tokenize, stable_hash, write_jsonl
from .embedding import BaseEmbedder, build_embedder


DENSE_WRITE_RETRY_ATTEMPTS = 3


@dataclass(slots=True)
class IndexBuildConfig:
    embedding_backend: str = "siliconflow"
    embedding_dimension: int | None = None
    embedding_model_name: str | None = None
    embedding_batch_size: int = 16
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    title_weight: int = 1
    heading_weight: int = 2
    summary_weight: int = 2
    content_weight: int = 3
    verbose: bool = False
    log_path: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_chunk_signature(chunks: Sequence[dict]) -> str:
    digest = hashlib.sha1()
    for chunk in chunks:
        digest.update(str(chunk.get("chunk_id", "")).encode("utf-8", errors="ignore"))
        digest.update(b"\x1f")
        digest.update(str(chunk.get("content_hash") or stable_hash(chunk_text(chunk), length=20)).encode("utf-8", errors="ignore"))
        digest.update(b"\x1e")
    return digest.hexdigest()[:24]


def dense_checkpoint_path(index_dir: Path) -> Path:
    return index_dir / "dense_checkpoint.json"


def build_dense_checkpoint_payload(
    *,
    chunk_count: int,
    completed_count: int,
    embedding_metadata: dict,
    chunk_signature: str,
    status: str,
    vectors_path: Path,
    batch_size: int,
    last_error: str | None = None,
) -> dict:
    payload = {
        "version": 1,
        "status": status,
        "chunk_count": chunk_count,
        "completed_count": completed_count,
        "embedding": embedding_metadata,
        "chunk_signature": chunk_signature,
        "vectors_path": vectors_path.as_posix(),
        "batch_size": batch_size,
        "updated_at": utc_now_iso(),
    }
    if last_error:
        payload["last_error"] = last_error
    return payload


def write_dense_checkpoint(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    last_error: Exception | None = None
    for attempt in range(1, DENSE_WRITE_RETRY_ATTEMPTS + 1):
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(path)
            return
        except (PermissionError, OSError) as exc:
            # Transient Windows file lock (antivirus / Search indexer) on the
            # atomic rename. Back off and retry instead of killing a long run.
            last_error = exc
            if attempt < DENSE_WRITE_RETRY_ATTEMPTS:
                time.sleep(0.5 * attempt)

    # Atomic replace kept failing; fall back to a direct in-place write so the
    # run can continue. A torn checkpoint only costs a few re-embedded chunks
    # on resume, which is far cheaper than aborting the whole build.
    try:
        path.write_text(serialized, encoding="utf-8")
    except (PermissionError, OSError):
        raise last_error if last_error is not None else RuntimeError(
            f"Không ghi được dense checkpoint tại {path.as_posix()}."
        )
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def read_dense_checkpoint(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def checkpoint_matches(
    checkpoint: dict,
    *,
    chunk_count: int,
    embedding_metadata: dict,
    chunk_signature: str,
) -> bool:
    checkpoint_embedding = checkpoint.get("embedding")
    if not isinstance(checkpoint_embedding, dict):
        return False

    comparable_keys = ("backend", "dimension", "model_name", "endpoint", "api_key_env")
    if int(checkpoint.get("chunk_count", -1)) != chunk_count:
        return False
    if checkpoint.get("chunk_signature") != chunk_signature:
        return False
    for key in comparable_keys:
        if checkpoint_embedding.get(key) != embedding_metadata.get(key):
            return False
    return True


def remove_dense_artifacts(vectors_path: Path, checkpoint_path: Path) -> None:
    if vectors_path.exists():
        vectors_path.unlink()
    if checkpoint_path.exists():
        checkpoint_path.unlink()


def log_event(config: IndexBuildConfig | None, message: str, *, always: bool = False) -> None:
    timestamped = f"[{utc_now_iso()}] {message}"
    if config is not None and config.log_path:
        log_path = Path(config.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(timestamped + "\n")
    if always or (config is not None and config.verbose):
        try:
            print(timestamped, flush=True)
        except OSError:
            if config is not None:
                config.verbose = False


def progress_enabled() -> bool:
    stream = getattr(sys, "stderr", None)
    if stream is None:
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError:
        return False


def reopen_dense_memmap(vectors_path: Path, expected_shape: tuple[int, int]) -> np.memmap:
    vectors = np.lib.format.open_memmap(vectors_path, mode="r+", dtype=np.float32)
    if tuple(vectors.shape) != expected_shape:
        raise RuntimeError(
            f"Existing vectors.npy shape {tuple(vectors.shape)} does not match expected shape {expected_shape}."
        )
    return vectors


def commit_dense_batch(
    *,
    vectors: np.memmap,
    vectors_path: Path,
    expected_shape: tuple[int, int],
    start: int,
    end: int,
    batch_vectors: np.ndarray,
    config: IndexBuildConfig,
) -> np.memmap:
    for attempt in range(1, DENSE_WRITE_RETRY_ATTEMPTS + 1):
        try:
            vectors[start:end] = batch_vectors
            vectors.flush()
            return vectors
        except OSError as exc:
            if attempt >= DENSE_WRITE_RETRY_ATTEMPTS:
                raise
            log_event(
                config,
                f"Dense vector commit failed for batch {start}:{end} on attempt "
                f"{attempt}/{DENSE_WRITE_RETRY_ATTEMPTS}: {exc}. Reopening vectors.npy and retrying.",
                always=True,
            )
            del vectors
            time.sleep(attempt)
            vectors = reopen_dense_memmap(vectors_path, expected_shape)
    raise RuntimeError(f"Không commit được dense batch {start}:{end} sau {DENSE_WRITE_RETRY_ATTEMPTS} lần thử.")


def chunk_text(chunk: dict) -> str:
    return str(chunk.get("text") or chunk.get("content") or "").strip()


def normalize_chunk_records(chunks: Sequence[dict]) -> list[dict]:
    normalized: list[dict] = []
    for index, chunk in enumerate(chunks, start=1):
        text = chunk_text(chunk)
        if not text:
            raise ValueError(f"Chunk ở vị trí {index} không có text/content.")
        content_hash = str(chunk.get("content_hash") or stable_hash(text, length=20))
        normalized_chunk = dict(chunk)
        normalized_chunk["chunk_id"] = str(chunk.get("chunk_id") or stable_hash(index, content_hash, length=24))
        normalized_chunk["content"] = str(chunk.get("content") or text).strip()
        normalized_chunk["text"] = text
        normalized_chunk["content_hash"] = content_hash
        normalized.append(normalized_chunk)
    return normalized


def build_dense_text(chunk: dict) -> str:
    if chunk.get("text"):
        return str(chunk["text"]).strip()

    blocks: list[str] = []
    if chunk.get("title"):
        blocks.append(chunk["title"])
    summary = (chunk.get("summary") or "").strip()
    if summary and summary != chunk.get("content", "") and len(summary) < 800:
        blocks.append(summary)
    if chunk.get("h2"):
        blocks.append(chunk["h2"])
    if chunk.get("h3"):
        blocks.append(chunk["h3"])
    blocks.append(chunk["content"])
    return "\n\n".join(part for part in blocks if part).strip()


def build_lexical_tokens(chunk: dict, config: IndexBuildConfig) -> list[str]:
    if chunk.get("text"):
        return simple_word_tokenize(str(chunk["text"]), fold_accents=True)

    tokens: list[str] = []

    def extend(text: str | None, weight: int) -> None:
        if not text or weight <= 0:
            return
        parsed = simple_word_tokenize(text, fold_accents=True)
        for _ in range(weight):
            tokens.extend(parsed)

    extend(chunk.get("title"), config.title_weight)
    extend(chunk.get("h2"), config.heading_weight)
    extend(chunk.get("h3"), config.heading_weight)
    extend(chunk.get("summary"), config.summary_weight)
    extend(chunk.get("content"), config.content_weight)
    return tokens


def enrich_chunk_records(chunks: Sequence[dict]) -> list[dict]:
    enriched: list[dict] = []
    for doc_idx, chunk in enumerate(chunks):
        copy = dict(chunk)
        copy["doc_idx"] = doc_idx
        enriched.append(copy)
    return enriched


def build_bm25_components(chunks: Sequence[dict], config: IndexBuildConfig) -> tuple[list[Counter[str]], list[int], Counter[str], float]:
    doc_term_freqs: list[Counter[str]] = []
    doc_lengths: list[int] = []
    df_counter: Counter[str] = Counter()

    for chunk in tqdm(chunks, desc="Tokenizing", unit="chunk", disable=not progress_enabled()):
        term_freq = Counter(build_lexical_tokens(chunk, config))
        doc_term_freqs.append(term_freq)
        length = sum(term_freq.values())
        doc_lengths.append(length)
        df_counter.update(term_freq.keys())

    avgdl = (sum(doc_lengths) / len(doc_lengths)) if doc_lengths else 0.0
    return doc_term_freqs, doc_lengths, df_counter, avgdl


def create_lexical_index(index_dir: Path, chunks: Sequence[dict], config: IndexBuildConfig) -> dict:
    log_event(config, f"Starting lexical index build for {len(chunks)} chunks.")
    doc_term_freqs, doc_lengths, df_counter, avgdl = build_bm25_components(chunks, config)
    db_path = index_dir / "lexical.sqlite3"
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=OFF;")
        connection.executescript(
            """
            CREATE TABLE docs (
                doc_idx INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL,
                token_count INTEGER NOT NULL
            );
            CREATE TABLE terms (
                term TEXT PRIMARY KEY,
                df INTEGER NOT NULL,
                idf REAL NOT NULL
            );
            CREATE TABLE postings (
                term TEXT NOT NULL,
                doc_idx INTEGER NOT NULL,
                tf INTEGER NOT NULL,
                PRIMARY KEY (term, doc_idx)
            );
            """
        )

        connection.executemany(
            "INSERT INTO docs (doc_idx, chunk_id, token_count) VALUES (?, ?, ?)",
            ((chunk["doc_idx"], chunk["chunk_id"], doc_lengths[chunk["doc_idx"]]) for chunk in chunks),
        )

        doc_count = len(chunks)
        connection.executemany(
            "INSERT INTO terms (term, df, idf) VALUES (?, ?, ?)",
            (
                (term, df, math.log1p((doc_count - df + 0.5) / (df + 0.5)))
                for term, df in tqdm(df_counter.items(), desc="Writing terms", unit="term", disable=not progress_enabled())
            ),
        )

        posting_rows: list[tuple[str, int, int]] = []
        for doc_idx, term_freq in tqdm(
            enumerate(doc_term_freqs),
            total=len(doc_term_freqs),
            desc="Writing postings",
            unit="chunk",
            disable=not progress_enabled(),
        ):
            posting_rows.extend((term, doc_idx, tf) for term, tf in term_freq.items())
            if len(posting_rows) >= 100_000:
                connection.executemany("INSERT INTO postings (term, doc_idx, tf) VALUES (?, ?, ?)", posting_rows)
                posting_rows.clear()
        if posting_rows:
            connection.executemany("INSERT INTO postings (term, doc_idx, tf) VALUES (?, ?, ?)", posting_rows)

        connection.execute("CREATE INDEX idx_postings_term ON postings(term)")
        connection.commit()
    finally:
        connection.close()

    return {
        "db_path": db_path.as_posix(),
        "doc_count": len(chunks),
        "avgdl": avgdl,
        "k1": config.bm25_k1,
        "b": config.bm25_b,
    }


def create_dense_index(index_dir: Path, chunks: Sequence[dict], embedder: BaseEmbedder, config: IndexBuildConfig) -> dict:
    batch_size = config.embedding_batch_size
    vectors_path = index_dir / "vectors.npy"
    checkpoint_path = dense_checkpoint_path(index_dir)
    embedding_metadata = embedder.metadata()
    chunk_count = len(chunks)
    chunk_signature = compute_chunk_signature(chunks)
    expected_shape = (chunk_count, int(embedder.dimension))
    completed_count = 0

    checkpoint = read_dense_checkpoint(checkpoint_path)
    if checkpoint and not checkpoint_matches(
        checkpoint,
        chunk_count=chunk_count,
        embedding_metadata=embedding_metadata,
        chunk_signature=chunk_signature,
    ):
        log_event(config, "Dense checkpoint metadata does not match current build input. Resetting partial dense artifacts.", always=True)
        remove_dense_artifacts(vectors_path, checkpoint_path)
        checkpoint = None

    vectors: np.memmap | None = None
    if checkpoint and vectors_path.exists():
        completed_count = max(0, min(int(checkpoint.get("completed_count", 0)), chunk_count))
        log_event(
            config,
            f"Resuming dense embedding from chunk {completed_count}/{chunk_count} using checkpoint {checkpoint_path.as_posix()}.",
            always=True,
        )
        vectors = reopen_dense_memmap(vectors_path, expected_shape)
        if checkpoint.get("status") == "complete" and completed_count == chunk_count:
            log_event(config, "Dense vectors already complete according to checkpoint. Reusing existing vectors.npy.", always=True)
            return {
                "vectors_path": vectors_path.as_posix(),
                "shape": list(expected_shape),
                "embedding": embedding_metadata,
            }
    if checkpoint is None:
        log_event(
            config,
            f"Starting dense embedding for {chunk_count} chunks with backend={embedding_metadata.get('backend')} "
            f"dimension={embedding_metadata.get('dimension')} batch_size={batch_size}.",
            always=True,
        )
        vectors = np.lib.format.open_memmap(vectors_path, mode="w+", dtype=np.float32, shape=expected_shape)
        write_dense_checkpoint(
            checkpoint_path,
            build_dense_checkpoint_payload(
                chunk_count=chunk_count,
                completed_count=0,
                embedding_metadata=embedding_metadata,
                chunk_signature=chunk_signature,
                status="in_progress",
                vectors_path=vectors_path,
                batch_size=batch_size,
            ),
        )
    assert vectors is not None

    try:
        for start in tqdm(
            range(completed_count, chunk_count, batch_size),
            desc="Embedding",
            unit="batch",
            disable=not progress_enabled(),
        ):
            end = min(start + batch_size, chunk_count)
            texts = [build_dense_text(chunk) for chunk in chunks[start:end]]
            batch_vectors = embedder.encode(texts, batch_size=batch_size).astype(np.float32, copy=False)
            if tuple(batch_vectors.shape) != (end - start, int(embedder.dimension)):
                raise RuntimeError(
                    f"Embedding backend returned shape {tuple(batch_vectors.shape)}; "
                    f"expected {(end - start, int(embedder.dimension))}."
                )
            vectors = commit_dense_batch(
                vectors=vectors,
                vectors_path=vectors_path,
                expected_shape=expected_shape,
                start=start,
                end=end,
                batch_vectors=batch_vectors,
                config=config,
            )
            completed_count = end
            write_dense_checkpoint(
                checkpoint_path,
                build_dense_checkpoint_payload(
                    chunk_count=chunk_count,
                    completed_count=completed_count,
                    embedding_metadata=embedding_metadata,
                    chunk_signature=chunk_signature,
                    status="in_progress",
                    vectors_path=vectors_path,
                    batch_size=batch_size,
                ),
            )
            log_event(config, f"Dense checkpoint committed: {completed_count}/{chunk_count} chunks encoded.")
    except Exception as exc:
        write_dense_checkpoint(
            checkpoint_path,
            build_dense_checkpoint_payload(
                chunk_count=chunk_count,
                completed_count=completed_count,
                embedding_metadata=embedding_metadata,
                chunk_signature=chunk_signature,
                status="paused",
                vectors_path=vectors_path,
                batch_size=batch_size,
                last_error=str(exc),
            ),
        )
        log_event(config, f"Dense embedding paused at {completed_count}/{chunk_count}: {exc}", always=True)
        raise
    finally:
        del vectors

    write_dense_checkpoint(
        checkpoint_path,
        build_dense_checkpoint_payload(
            chunk_count=chunk_count,
            completed_count=chunk_count,
            embedding_metadata=embedding_metadata,
            chunk_signature=chunk_signature,
            status="complete",
            vectors_path=vectors_path,
            batch_size=batch_size,
        ),
    )
    log_event(config, f"Dense embedding completed for {chunk_count}/{chunk_count} chunks.", always=True)
    return {
        "vectors_path": vectors_path.as_posix(),
        "shape": list(expected_shape),
        "embedding": embedding_metadata,
    }


def build_hybrid_index(chunks_path: Path, index_dir: Path, *, config: IndexBuildConfig | None = None) -> dict:
    active_config = config or IndexBuildConfig()
    log_event(active_config, f"Loading chunks from {chunks_path.as_posix()}.", always=True)
    raw_chunks = list(iter_jsonl(chunks_path))
    chunks = enrich_chunk_records(normalize_chunk_records(raw_chunks))
    index_dir.mkdir(parents=True, exist_ok=True)

    chunk_store_path = index_dir / "chunks.jsonl"
    write_jsonl(chunk_store_path, chunks)
    log_event(active_config, f"Wrote chunk store with {len(chunks)} chunks to {chunk_store_path.as_posix()}.", always=True)

    embedder = build_embedder(
        active_config.embedding_backend,
        dimension=active_config.embedding_dimension,
        model_name=active_config.embedding_model_name,
    )
    dense_manifest = create_dense_index(index_dir, chunks, embedder, active_config)
    lexical_manifest = create_lexical_index(index_dir, chunks, active_config)

    manifest = {
        "index_id": stable_hash(chunks_path.as_posix(), json.dumps(asdict(active_config), sort_keys=True), length=20),
        "chunks_path": chunk_store_path.as_posix(),
        "chunk_count": len(chunks),
        "dense": dense_manifest,
        "lexical": lexical_manifest,
        "config": asdict(active_config),
    }
    manifest_path = index_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log_event(active_config, f"Hybrid index manifest written to {manifest_path.as_posix()}.", always=True)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build index hybrid local.")
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--embedding-backend", default="siliconflow")
    parser.add_argument("--embedding-dimension", type=int)
    parser.add_argument("--embedding-model-name")
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    parser.add_argument("--bm25-k1", type=float, default=1.5)
    parser.add_argument("--bm25-b", type=float, default=0.75)
    parser.add_argument("--title-weight", type=int, default=1)
    parser.add_argument("--heading-weight", type=int, default=2)
    parser.add_argument("--summary-weight", type=int, default=2)
    parser.add_argument("--content-weight", type=int, default=3)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--log-path", type=Path)
    return parser.parse_args()


def main() -> None:
    configure_utf8_stdio()
    load_project_env()
    args = parse_args()
    config = IndexBuildConfig(
        embedding_backend=args.embedding_backend,
        embedding_dimension=args.embedding_dimension,
        embedding_model_name=args.embedding_model_name,
        embedding_batch_size=args.embedding_batch_size,
        bm25_k1=args.bm25_k1,
        bm25_b=args.bm25_b,
        title_weight=args.title_weight,
        heading_weight=args.heading_weight,
        summary_weight=args.summary_weight,
        content_weight=args.content_weight,
        verbose=args.verbose,
        log_path=(args.log_path or (args.index_dir / "build.log")).as_posix(),
    )
    manifest = build_hybrid_index(args.chunks, args.index_dir, config=config)
    try:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    except OSError:
        pass


if __name__ == "__main__":
    main()
