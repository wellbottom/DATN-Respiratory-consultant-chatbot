from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass(slots=True)
class SiliconFlowEmbeddingConfig:
    api_key: str
    model_name: str
    endpoint: str
    dimension: int
    timeout_seconds: float
    request_batch_size: int
    remote_max_batch_size: int
    invalid_json_retries: int = 5
    invalid_json_backoff_seconds: float = 2.0
    http_retry_total: int = 8


class SiliconFlowEmbedder:
    def __init__(self, config: SiliconFlowEmbeddingConfig) -> None:
        self.config = config

        retry = Retry(
            total=self.config.http_retry_total,
            connect=self.config.http_retry_total,
            read=self.config.http_retry_total,
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
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
        )
        self._session = session

    @staticmethod
    def _batched(items: Sequence[str], batch_size: int) -> list[Sequence[str]]:
        return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]

    def _payload(self, texts: Sequence[str]) -> dict:
        return {
            "model": self.config.model_name,
            "input": list(texts),
            "encoding_format": "float",
            "dimensions": self.config.dimension,
        }

    @staticmethod
    def _response_preview(response: requests.Response, *, limit: int = 500) -> str:
        return " ".join(response.text[:limit].split())

    @staticmethod
    def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vectors / norms

    def _post_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        last_decode_error: Exception | None = None
        payload: dict | None = None
        response: requests.Response | None = None

        max_attempts = max(1, int(self.config.invalid_json_retries))
        for attempt in range(1, max_attempts + 1):
            response = self._session.post(
                self.config.endpoint,
                json=self._payload(texts),
                timeout=self.config.timeout_seconds,
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
                        message = str(error.get("message") or json.dumps(error, ensure_ascii=False))
                    elif error:
                        message = str(error)
                raise RuntimeError(f"Yêu cầu embedding tới SiliconFlow thất bại ({response.status_code}): {message}")

            try:
                payload = response.json()
                break
            except ValueError as exc:
                last_decode_error = exc
                if attempt >= max_attempts:
                    preview = self._response_preview(response)
                    raise RuntimeError(
                        f"SiliconFlow trả về JSON không hợp lệ sau {attempt} lần thử với batch_size={len(texts)}: "
                        f"{exc}. Phần đầu phản hồi: {preview!r}"
                    ) from exc

        if not isinstance(payload, dict):
            preview = self._response_preview(response) if response is not None else ""
            if last_decode_error is not None:
                raise RuntimeError(
                    f"Payload phản hồi từ SiliconFlow không phải đối tượng JSON sau nhiều lần thử. "
                    f"Lỗi giải mã cuối cùng: {last_decode_error}. Phần đầu phản hồi: {preview!r}"
                ) from last_decode_error
            raise RuntimeError(f"Payload phản hồi từ SiliconFlow không phải đối tượng JSON. Phần đầu phản hồi: {preview!r}")

        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Phản hồi embedding từ SiliconFlow thiếu mảng 'data' hợp lệ.")

        ordered = sorted(data, key=lambda item: item.get("index", 0))
        embeddings = [item.get("embedding") for item in ordered]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Kỳ vọng nhận {len(texts)} embedding từ SiliconFlow nhưng chỉ có {len(embeddings)}."
            )

        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim != 2:
            raise RuntimeError("Phản hồi embedding từ SiliconFlow không trả về mảng số thực 2 chiều.")
        if vectors.shape[1] != self.config.dimension:
            raise RuntimeError(
                f"SiliconFlow trả về số chiều {vectors.shape[1]}, trong khi hệ thống cần {self.config.dimension}."
            )
        return self._l2_normalize(vectors)

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        batch_size = max(1, min(self.config.request_batch_size, self.config.remote_max_batch_size))
        rows: list[np.ndarray] = []
        for batch in self._batched(list(texts), batch_size):
            rows.append(self._post_embeddings(batch))
        return np.vstack(rows).astype(np.float32, copy=False).tolist()
