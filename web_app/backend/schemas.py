from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list)


class RouteDebug(BaseModel):
    collection_name: str | None = None
    knowledge_base: str | None = None
    corpora: list[str]
    intent: str
    section_types: list[str]
    reasons: list[str]


class SourceChunk(BaseModel):
    chunk_id: str
    candidate_chunk_index: int
    candidate_chunk_total: int
    content: str | None = None


class SourceSection(BaseModel):
    section_id: str
    corpus: str
    title: str
    h2: str | None = None
    h3: str | None = None
    section_type: str
    source_path: str
    source_url: str | None = None
    source_url_kind: str | None = None
    rerank_score: float | None = None
    vector_score: float | None = None
    vector_distance: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    chunk_count: int
    chunks: list[SourceChunk]


class ChatResponse(BaseModel):
    answer: str
    user_query: str
    route: RouteDebug
    sources: list[SourceSection]
    diagnostics: dict[str, Any]


class NearbyService(BaseModel):
    id: str
    name: str
    type: str
    category: str
    latitude: float
    longitude: float
    distance_km: float
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    opening_hours: str | None = None
    source_url: str
    tags: dict[str, str] = Field(default_factory=dict)


class NearbyServicesResponse(BaseModel):
    query_latitude: float
    query_longitude: float
    category: str
    radius_m: int
    source: str
    results: list[NearbyService]


class CreateConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Tiêu đề không được để trống.")
        return cleaned


class UpdateConversationRequest(BaseModel):
    is_public: bool


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConversationSummary(BaseModel):
    id: str
    title: str
    is_public: bool
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    user_input_id: str
    response_id: str | None = None
    route: RouteDebug | None = None
    sources: list[SourceSection] = Field(default_factory=list)
    diagnostics: dict[str, Any] | None = None


class ConversationDetail(BaseModel):
    id: str
    title: str
    is_public: bool
    created_at: datetime
    updated_at: datetime
    message_count: int
    messages: list[ConversationMessage]


class MessageResponse(BaseModel):
    conversation: ConversationSummary
    user_message: ConversationMessage
    assistant_message: ConversationMessage
    route: RouteDebug
    sources: list[SourceSection]
    diagnostics: dict[str, Any]
