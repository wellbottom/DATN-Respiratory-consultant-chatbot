from __future__ import annotations

import argparse

import json
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .common import batched, configure_utf8_stdio, load_project_env, simple_word_tokenize


class BaseEmbedder(ABC):
    """Abstract embedding backend used by the indexer."""

    name: str
    dimension: int

    @abstractmethod
    def encode(self, texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray:
        raise NotImplementedError

    def encode_queries(self, texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray:
        return self.encode(texts, batch_size=batch_size)

    def metadata(self) -> dict:
        return {
            "backend": self.name,
            "dimension": self.dimension,
        }


class SiliconFlowEmbedder(BaseEmbedder):
    """Remote embedding backend using the SiliconFlow OpenAI-compatible embeddings API."""

    DEFAULT_ENDPOINT = "https://api.siliconflow.com/v1/embeddings"
    DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"
    DEFAULT_DIMENSION = 2560
    DEFAULT_TIMEOUT_SECONDS = 120.0
    DEFAULT_MAX_BATCH_SIZE = 32
    DEFAULT_INVALID_JSON_RETRIES = 5
    DEFAULT_INVALID_JSON_BACKOFF_SECONDS = 2.0
    DEFAULT_HTTP_RETRY_TOTAL = 8

    def __init__(
        self,
        model_name: str | None = None,
        *,
        dimension: int | None = None,
        endpoint: str | None = None,
        api_key_env: str = "SILICONFLOW_API_KEY",
        timeout_seconds: float | None = None,
        max_batch_size: int | None = None,
    ) -> None:
        load_project_env()
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Thiếu biến môi trường {api_key_env}. "
                "Hãy đặt biến này trước khi dùng backend=siliconflow."
            )

        env_dimension = os.getenv("SILICONFLOW_EMBEDDING_DIMENSIONS")
        resolved_dimension = dimension
        if resolved_dimension is None and env_dimension:
            resolved_dimension = int(env_dimension)
        if resolved_dimension is None:
            resolved_dimension = self.DEFAULT_DIMENSION

        env_model = os.getenv("SILICONFLOW_EMBEDDING_MODEL")
        env_endpoint = os.getenv("SILICONFLOW_EMBEDDINGS_URL")
        env_timeout = os.getenv("SILICONFLOW_TIMEOUT_SECONDS")
        env_max_batch = os.getenv("SILICONFLOW_MAX_BATCH_SIZE")

        self.name = "siliconflow"
        self.dimension = int(resolved_dimension)
        self._model_name = model_name or env_model or self.DEFAULT_MODEL
        self._endpoint = endpoint or env_endpoint or self.DEFAULT_ENDPOINT
        self._timeout_seconds = float(timeout_seconds or env_timeout or self.DEFAULT_TIMEOUT_SECONDS)
        self._max_batch_size = int(max_batch_size or env_max_batch or self.DEFAULT_MAX_BATCH_SIZE)
        self._api_key_env = api_key_env
        self._invalid_json_retries = int(os.getenv("SILICONFLOW_INVALID_JSON_RETRIES", self.DEFAULT_INVALID_JSON_RETRIES))
        self._invalid_json_backoff_seconds = float(
            os.getenv("SILICONFLOW_INVALID_JSON_BACKOFF_SECONDS", self.DEFAULT_INVALID_JSON_BACKOFF_SECONDS)
        )
        self._http_retry_total = int(os.getenv("SILICONFLOW_HTTP_RETRY_TOTAL", self.DEFAULT_HTTP_RETRY_TOTAL))

        retry = Retry(
            total=self._http_retry_total,
            connect=self._http_retry_total,
            read=self._http_retry_total,
            backoff_factor=1.0,
            status_forcelist=[408, 429, 500, 502, 503, 504, 520, 521, 522, 524],
            allowed_methods=["POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        self._session = session

    def _payload(self, texts: Sequence[str]) -> dict:
        return {
            "model": self._model_name,
            "input": list(texts),
            "encoding_format": "float",
            "dimensions": self.dimension,
        }

    @staticmethod
    def _response_preview(response: requests.Response, *, limit: int = 500) -> str:
        text = response.text[:limit]
        return " ".join(text.split())

    def _post_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        last_decode_error: Exception | None = None
        response: requests.Response | None = None
        payload: dict | None = None
        max_attempts = max(1, self._invalid_json_retries)

        for attempt in range(1, max_attempts + 1):
            response = self._session.post(
                self._endpoint,
                json=self._payload(texts),
                timeout=self._timeout_seconds,
            )
            if response.status_code >= 400:
                message = response.text
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if isinstance(payload, dict):
                    error = payload.get("error")
                    if isinstance(error, dict):
                        message = error.get("message") or json.dumps(error, ensure_ascii=False)
                    elif error:
                        message = str(error)
                raise RuntimeError(f"SiliconFlow embeddings request failed ({response.status_code}): {message}")

            try:
                payload = response.json()
                break
            except ValueError as exc:
                last_decode_error = exc
                if attempt >= max_attempts:
                    preview = self._response_preview(response)
                    raise RuntimeError(
                        f"SiliconFlow returned invalid JSON after {attempt} attempts for batch_size={len(texts)}: "
                        f"{exc}. Response prefix: {preview!r}"
                    ) from exc
                time.sleep(self._invalid_json_backoff_seconds * attempt)

        if not isinstance(payload, dict):
            preview = self._response_preview(response) if response is not None else ""
            if last_decode_error is not None:
                raise RuntimeError(
                    f"SiliconFlow response payload was not a JSON object after retries. "
                    f"Last decode error: {last_decode_error}. Response prefix: {preview!r}"
                ) from last_decode_error
            raise RuntimeError(f"SiliconFlow response payload was not a JSON object. Response prefix: {preview!r}")

        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("SiliconFlow embeddings response is missing a valid 'data' array.")

        ordered = sorted(data, key=lambda item: item.get("index", 0))
        embeddings = [item.get("embedding") for item in ordered]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Expected {len(texts)} embeddings from SiliconFlow, received {len(embeddings)}."
            )

        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim != 2:
            raise RuntimeError("SiliconFlow embeddings response did not return a 2D float array.")
        if vectors.shape[1] != self.dimension:
            raise RuntimeError(
                f"SiliconFlow returned dimension {vectors.shape[1]}, expected {self.dimension}."
            )
        return self._l2_normalize(vectors)

    @staticmethod
    def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vectors / norms

    def encode(self, texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        effective_batch_size = max(1, min(batch_size, self._max_batch_size))
        rows: list[np.ndarray] = []
        for batch in batched(texts, effective_batch_size):
            rows.append(self._post_embeddings(batch))
        return np.vstack(rows).astype(np.float32, copy=False)

    def metadata(self) -> dict:
        metadata = super().metadata()
        metadata.update(
            {
                "model_name": self._model_name,
                "endpoint": self._endpoint,
                "api_key_env": self._api_key_env,
                "timeout_seconds": self._timeout_seconds,
                "max_batch_size": self._max_batch_size,
                "http_retry_total": self._http_retry_total,
                "invalid_json_retries": self._invalid_json_retries,
            }
        )
        return metadata


class OllamaEmbedder(BaseEmbedder):
    """Local embedding backend using the Ollama HTTP API."""

    DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/embed"
    DEFAULT_MODEL = "qwen3-embedding:4b"
    DEFAULT_TIMEOUT_SECONDS = 300.0
    DEFAULT_MAX_BATCH_SIZE = 8
    DEFAULT_INVALID_JSON_RETRIES = 3
    DEFAULT_HTTP_RETRY_TOTAL = 4
    DEFAULT_REQUEST_ERROR_RETRIES = 4

    def __init__(
        self,
        model_name: str | None = None,
        *,
        dimension: int | None = None,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
        max_batch_size: int | None = None,
    ) -> None:
        load_project_env()
        env_dimension = os.getenv("OLLAMA_EMBEDDING_DIMENSIONS") or os.getenv("OLLAMA_EMBEDDING_DIMENSION")
        resolved_dimension = dimension
        if resolved_dimension is None and env_dimension:
            resolved_dimension = int(env_dimension)

        env_model = os.getenv("OLLAMA_EMBEDDING_MODEL") or os.getenv("OLLAMA_MODEL")
        env_endpoint = os.getenv("OLLAMA_EMBEDDINGS_URL") or os.getenv("OLLAMA_EMBEDDING_URL")
        env_timeout = os.getenv("OLLAMA_TIMEOUT_SECONDS")
        env_max_batch = os.getenv("OLLAMA_MAX_BATCH_SIZE")

        self.name = "ollama"
        self.dimension = int(resolved_dimension) if resolved_dimension is not None else 0
        self._model_name = model_name or env_model or self.DEFAULT_MODEL
        self._endpoint = endpoint or env_endpoint or self.DEFAULT_ENDPOINT
        self._timeout_seconds = float(timeout_seconds or env_timeout or self.DEFAULT_TIMEOUT_SECONDS)
        self._max_batch_size = int(max_batch_size or env_max_batch or self.DEFAULT_MAX_BATCH_SIZE)
        self._invalid_json_retries = int(os.getenv("OLLAMA_INVALID_JSON_RETRIES", self.DEFAULT_INVALID_JSON_RETRIES))
        self._request_error_retries = int(os.getenv("OLLAMA_REQUEST_ERROR_RETRIES", self.DEFAULT_REQUEST_ERROR_RETRIES))
        self._http_retry_total = int(os.getenv("OLLAMA_HTTP_RETRY_TOTAL", self.DEFAULT_HTTP_RETRY_TOTAL))
        self._session = self._build_session()

        if self.dimension <= 0:
            self.dimension = self._probe_dimension()

    def _payload(self, texts: Sequence[str]) -> dict:
        return {
            "model": self._model_name,
            "input": list(texts),
        }

    def _build_session(self) -> requests.Session:
        retry = Retry(
            total=self._http_retry_total,
            connect=self._http_retry_total,
            read=self._http_retry_total,
            backoff_factor=1.0,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"Content-Type": "application/json"})
        return session

    @staticmethod
    def _response_preview(response: requests.Response, *, limit: int = 500) -> str:
        text = response.text[:limit]
        return " ".join(text.split())

    @staticmethod
    def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vectors / norms

    def _decode_embeddings_payload(self, payload: dict, texts: Sequence[str]) -> np.ndarray:
        embeddings = payload.get("embeddings")
        if embeddings is None and len(texts) == 1 and payload.get("embedding") is not None:
            embeddings = [payload["embedding"]]
        if not isinstance(embeddings, list):
            raise RuntimeError("Ollama embeddings response is missing a valid 'embeddings' array.")

        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.ndim != 2:
            raise RuntimeError("Ollama embeddings response did not return a 2D float array.")
        if vectors.shape[0] != len(texts):
            raise RuntimeError(f"Expected {len(texts)} Ollama embeddings, received {vectors.shape[0]}.")
        if self.dimension and vectors.shape[1] != self.dimension:
            raise RuntimeError(
                f"Ollama returned dimension {vectors.shape[1]}, expected {self.dimension}."
            )
        if self.dimension <= 0:
            self.dimension = int(vectors.shape[1])
        return self._l2_normalize(vectors)

    def _post_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        payload: dict | None = None
        response: requests.Response | None = None
        last_decode_error: Exception | None = None
        max_attempts = max(1, self._invalid_json_retries)

        for attempt in range(1, max_attempts + 1):
            response = self._session.post(
                self._endpoint,
                json=self._payload(texts),
                timeout=self._timeout_seconds,
            )
            if response.status_code >= 400:
                message = response.text
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if isinstance(payload, dict) and payload.get("error"):
                    message = str(payload.get("error"))
                raise RuntimeError(f"Ollama embeddings request failed ({response.status_code}): {message}")

            try:
                payload = response.json()
                break
            except ValueError as exc:
                last_decode_error = exc
                if attempt >= max_attempts:
                    preview = self._response_preview(response)
                    raise RuntimeError(
                        f"Ollama returned invalid JSON after {attempt} attempts for batch_size={len(texts)}: "
                        f"{exc}. Response prefix: {preview!r}"
                    ) from exc
                time.sleep(attempt)

        if not isinstance(payload, dict):
            preview = self._response_preview(response) if response is not None else ""
            if last_decode_error is not None:
                raise RuntimeError(
                    f"Ollama response payload was not a JSON object after retries. "
                    f"Last decode error: {last_decode_error}. Response prefix: {preview!r}"
                ) from last_decode_error
            raise RuntimeError(f"Ollama response payload was not a JSON object. Response prefix: {preview!r}")

        return self._decode_embeddings_payload(payload, texts)

    def _probe_dimension(self) -> int:
        vectors = self._post_embeddings(["dimension probe"])
        if vectors.ndim != 2 or vectors.shape[0] != 1 or vectors.shape[1] <= 0:
            raise RuntimeError("Failed to infer embedding dimension from Ollama.")
        return int(vectors.shape[1])

    def encode(self, texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        effective_batch_size = max(1, min(batch_size, self._max_batch_size))
        rows: list[np.ndarray] = []
        for batch in batched(texts, effective_batch_size):
            for attempt in range(1, self._request_error_retries + 1):
                try:
                    rows.append(self._post_embeddings(batch))
                    break
                except (requests.RequestException, OSError) as exc:
                    self._session.close()
                    self._session = self._build_session()
                    if attempt >= self._request_error_retries:
                        raise RuntimeError(
                            f"Ollama embeddings request failed after {attempt} attempts for batch_size={len(batch)}: {exc}"
                        ) from exc
                    time.sleep(attempt)
        return np.vstack(rows).astype(np.float32, copy=False)

    def metadata(self) -> dict:
        metadata = super().metadata()
        metadata.update(
            {
                "model_name": self._model_name,
                "endpoint": self._endpoint,
                "timeout_seconds": self._timeout_seconds,
                "max_batch_size": self._max_batch_size,
                "http_retry_total": self._http_retry_total,
                "invalid_json_retries": self._invalid_json_retries,
                "request_error_retries": self._request_error_retries,
            }
        )
        return metadata


def build_embedder(
    backend: str,
    *,
    dimension: int | None = None,
    model_name: str | None = None,
    use_bigrams: bool | None = None,
    endpoint: str | None = None,
    api_key_env: str = "SILICONFLOW_API_KEY",
    timeout_seconds: float | None = None,
    max_batch_size: int | None = None,
) -> BaseEmbedder:
    normalized_backend = backend.casefold()
    
    if normalized_backend in {"ollama", "local-ollama"}:
        return OllamaEmbedder(
            model_name=model_name,
            dimension=dimension,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_batch_size=max_batch_size,
        )
    if normalized_backend in {"siliconflow", "qwen", "qwen3"}:
        return SiliconFlowEmbedder(
            model_name=model_name,
            dimension=dimension,
            endpoint=endpoint,
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
            max_batch_size=max_batch_size,
        )
    raise ValueError(f"Backend embedding không hỗ trợ: {backend}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tạo embeddings cho file chunks JSONL.")
    parser.add_argument("--backend", default="siliconflow")
    parser.add_argument("--dimension", type=int)
    parser.add_argument("--model-name")
    parser.add_argument("--input", type=Path, required=True, help="File chunks JSONL đầu vào.")
    parser.add_argument("--output", type=Path, required=True, help="File .npy đầu ra.")
    parser.add_argument("--batch-size", type=int, default=128)
    return parser.parse_args()


def main() -> None:
    from .common import iter_jsonl

    configure_utf8_stdio()
    load_project_env()
    args = parse_args()
    embedder = build_embedder(args.backend, dimension=args.dimension, model_name=args.model_name)
    rows = list(iter_jsonl(args.input))
    texts = [row.get("text", row.get("content", "")) for row in rows]
    vectors = embedder.encode(texts, batch_size=args.batch_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, vectors)
    manifest = {
        "count": len(texts),
        "vectors_path": args.output.as_posix(),
        "embedding": embedder.metadata(),
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
