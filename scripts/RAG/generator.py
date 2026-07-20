from __future__ import annotations

from typing import Any, Sequence

import requests


class RequestLLMClient:
    def __init__(
        self,
        providers: Sequence[dict[str, Any]],
        *,
        model: str,
        timeout_seconds: float = 90.0,
        session: Any | None = None,
    ) -> None:
        self.providers = tuple(dict(provider) for provider in providers)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    @classmethod
    def from_settings(cls, settings: Any, *, session: Any | None = None) -> "RequestLLMClient":
        return cls(
            settings.llm_providers,
            model=settings.llm_model,
            timeout_seconds=settings.request_timeout_seconds,
            session=session,
        )

    def provider_order(self) -> tuple[str, ...]:
        return tuple(str(provider.get("name") or provider.get("endpoint") or "llm") for provider in self.providers)

    @staticmethod
    def _response_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if payload.get("message"):
                return str(payload["message"])
            return str(payload)
        return " ".join(str(response.text or response.reason or "").split())

    @classmethod
    def describe_error(cls, exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if isinstance(response, requests.Response):
            message = cls._response_message(response)
            status = getattr(response, "status_code", None)
            return f"{status}: {message[:280]}" if status else message[:300]
        return str(exc)

    @classmethod
    def is_request_too_large(cls, exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if isinstance(response, requests.Response) and response.status_code == 413:
            return True
        message = cls.describe_error(exc).lower()
        return any(
            marker in message
            for marker in (
                "request too large",
                "reduce your message size",
                "context length",
                "maximum context",
                "token limit",
                "too many tokens",
            )
        )

    @staticmethod
    def _coerce_message_content(content: Any, *, provider_name: str) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
                if item_type != "text":
                    continue
                text_parts.append(str(item.get("text") if isinstance(item, dict) else getattr(item, "text", "")))
            return "\n".join(part for part in text_parts if part).strip()
        raise RuntimeError(f"Định dạng phản hồi từ {provider_name} không được hỗ trợ.")

    def _extract_chat_content(self, payload: dict[str, Any], *, provider_name: str) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"{provider_name} không trả về lựa chọn nào.")
        first_choice = choices[0]
        message = first_choice.get("message") if isinstance(first_choice, dict) else getattr(first_choice, "message", None)
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        content_text = self._coerce_message_content(content, provider_name=provider_name)
        if not content_text:
            raise RuntimeError(f"{provider_name} trả về nội dung rỗng.")
        return content_text

    @staticmethod
    def _headers(provider: dict[str, Any]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update({str(key): str(value) for key, value in dict(provider.get("headers") or {}).items()})
        api_key = str(provider.get("api_key") or "").strip()
        if api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _payload(self, provider: dict[str, Any], messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = {
            "model": str(provider.get("model") or self.model),
            "messages": messages,
        }
        payload.update(dict(provider.get("extra_body") or {}))
        return payload

    def chat(self, messages: list[dict[str, str]]) -> str:
        errors: list[str] = []
        for provider in self.providers:
            name = str(provider.get("name") or provider.get("endpoint") or "llm")
            try:
                response = self.session.post(
                    str(provider["endpoint"]),
                    headers=self._headers(provider),
                    json=self._payload(provider, messages),
                    timeout=float(provider.get("timeout_seconds") or self.timeout_seconds),
                )
                response.raise_for_status()
                return self._extract_chat_content(response.json(), provider_name=name)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {self.describe_error(exc)}")
        raise RuntimeError("Tất cả provider LLM đều thất bại: " + "; ".join(errors))

    @staticmethod
    def _contextualize_system_prompt() -> str:
        return (
            "Bạn là bộ viết lại truy vấn cho hệ thống RAG y khoa. "
            "Hãy viết lại câu hỏi mới nhất thành một truy vấn độc lập, đủ ngữ cảnh, bằng tiếng Việt. "
            "Không trả lời câu hỏi. Không thêm giải thích. Chỉ trả về đúng một truy vấn hoàn chỉnh."
        )

    @staticmethod
    def _answer_system_prompt() -> str:
        return (
            "Bạn là trợ lý thông tin y khoa dựa trên truy xuất tài liệu. "
            "Chỉ dùng phần 'Ngữ cảnh y khoa được truy xuất' làm nguồn kiến thức y khoa. "
            "Không tự chẩn đoán, không kê đơn, không yêu cầu người dùng tự mua thuốc. "
            "Nếu ngữ cảnh không đủ, hãy nói rõ dữ liệu hiện tại chưa đủ. "
            "Nếu có dấu hiệu nguy cấp, hãy khuyên liên hệ cơ sở y tế ngay. "
            "Trả lời bằng tiếng Việt rõ ràng và ngắn gọn."
        )

    def contextualize_query_clean(self, *, user_query: str, conversation_context: str) -> str:
        if not conversation_context.strip():
            return user_query
        rewritten = self.chat(
            [
                {"role": "system", "content": self._contextualize_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        f"Lịch sử hội thoại gần đây:\n{conversation_context}\n\n"
                        f"Câu hỏi mới nhất:\n{user_query}\n\n"
                        "Viết lại câu hỏi mới nhất thành truy vấn độc lập để truy xuất tài liệu."
                    ),
                },
            ]
        )
        normalized = " ".join(line.strip() for line in rewritten.splitlines() if line.strip())
        normalized = normalized.removeprefix("Truy vấn:").removeprefix("Query:").strip()
        return normalized.strip('"').strip()

    def answer_clean(
        self,
        *,
        user_query: str,
        medical_context: str,
        conversation_context: str,
        contextual_query: str,
    ) -> str:
        return self.chat(
            [
                {"role": "system", "content": self._answer_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        f"Lịch sử hội thoại gần đây:\n{conversation_context}\n\n"
                        f"Câu hỏi hiện tại:\n{user_query}\n\n"
                        f"Truy vấn đã ngữ cảnh hóa để retrieval:\n{contextual_query}\n\n"
                        f"Ngữ cảnh y khoa được truy xuất:\n{medical_context}"
                    ),
                },
            ]
        )
