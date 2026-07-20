from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any, NoReturn

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .auth import AuthenticatedRequest, ClerkTokenVerifier
from .database import Base, configure_database, get_db, get_engine
from .models import Conversation, Response as AssistantResponse, User, UserInput
from .nearby_services import fetch_nearby_services
from scripts.RAG.source_metadata import SourceUrlResolver
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    CreateConversationRequest,
    MessageRequest,
    MessageResponse,
    NearbyServicesResponse,
    RouteDebug,
    SourceSection,
    UpdateConversationRequest,
)
from .services import MedicalAssistantService
from .settings import load_settings
from scripts.RAG.common import iter_jsonl

settings = load_settings()
service = MedicalAssistantService(settings)
configure_database(settings)
Base.metadata.create_all(bind=get_engine())
clerk_verifier = ClerkTokenVerifier(settings)
source_url_resolver = SourceUrlResolver()
_chunk_content_cache: dict[str, str] | None = None

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.clerk_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _derive_title(message: str) -> str:
    cleaned = _collapse_spaces(message)
    if not cleaned:
        return "Cuộc trò chuyện mới"
    if len(cleaned) <= 72:
        return cleaned
    return cleaned[:69].rstrip() + "..."


def _ensure_clerk_enabled() -> None:
    if clerk_verifier.is_enabled():
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Clerk chưa được cấu hình xác thực. Hãy đặt CLERK_JWT_KEY hoặc CLERK_FRONTEND_API_URL/CLERK_JWKS_URL.",
    )


def _require_auth(request: Request) -> AuthenticatedRequest:
    _ensure_clerk_enabled()
    auth = clerk_verifier.verify_request(request)
    if auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bạn cần đăng nhập để tiếp tục.")
    return auth


def _optional_auth(request: Request) -> AuthenticatedRequest | None:
    if not clerk_verifier.is_enabled():
        return None
    try:
        return clerk_verifier.verify_request(request)
    except HTTPException:
        return None


def _get_or_create_user(db: Session, auth: AuthenticatedRequest) -> User:
    user = db.scalar(select(User).where(User.clerk_user_id == auth.clerk_user_id))
    if user is None:
        user = User(clerk_user_id=auth.clerk_user_id)
        db.add(user)
        db.flush()
        return user

    user.updated_at = _utcnow()
    db.flush()
    return user


def _conversation_query() -> Any:
    return select(Conversation).options(
        selectinload(Conversation.user_inputs).selectinload(UserInput.response),
    )


def _load_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.scalar(_conversation_query().where(Conversation.id == conversation_id))
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cuộc trò chuyện.")
    return conversation


def _ensure_owner(conversation: Conversation, user: User) -> None:
    if conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cuộc trò chuyện.")


def _not_found_conversation() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cuộc trò chuyện.")


def _ensure_view_access(conversation: Conversation, auth: AuthenticatedRequest | None, db: Session) -> bool:
    if auth is None:
        if conversation.is_public:
            return False
        raise _not_found_conversation()

    user = db.scalar(select(User).where(User.clerk_user_id == auth.clerk_user_id))
    is_owner = user is not None and user.id == conversation.user_id
    if conversation.is_public or is_owner:
        return is_owner

    raise _not_found_conversation()


def _route_from_payload(payload: dict[str, Any] | None) -> RouteDebug | None:
    if payload is None:
        return None
    return RouteDebug.model_validate(payload)


def _enrich_source_payload(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    resolution = source_url_resolver.resolve(
        source_path=enriched.get("source_path"),
        title=enriched.get("title"),
        existing_url=enriched.get("source_url"),
        existing_url_kind=enriched.get("source_url_kind"),
    )
    enriched["source_url"] = resolution.source_url
    enriched["source_url_kind"] = resolution.source_url_kind
    for chunk in enriched.get("chunks") or []:
        if isinstance(chunk, dict) and not chunk.get("content"):
            chunk["content"] = _chunk_content_by_id().get(str(chunk.get("chunk_id") or ""), "")
    return enriched


def _chunk_content_by_id() -> dict[str, str]:
    global _chunk_content_cache
    if _chunk_content_cache is not None:
        return _chunk_content_cache

    path = settings.section_store_path
    if path is None or not Path(path).exists():
        _chunk_content_cache = {}
        return _chunk_content_cache

    _chunk_content_cache = {
        str(row.get("chunk_id") or ""): str(row.get("content") or row.get("text") or "")
        for row in iter_jsonl(Path(path))
        if row.get("chunk_id")
    }
    return _chunk_content_cache


def _sources_from_payload(payload: list[Any] | None) -> list[SourceSection]:
    if not payload:
        return []
    enriched_items: list[SourceSection] = []
    for item in payload:
        if isinstance(item, dict):
            enriched_items.append(SourceSection.model_validate(_enrich_source_payload(item)))
        else:
            enriched_items.append(SourceSection.model_validate(item))
    return enriched_items


def _message_from_user_input(user_input: UserInput) -> ConversationMessage:
    return ConversationMessage(
        id=user_input.id,
        role="user",
        content=user_input.content,
        created_at=user_input.created_at,
        user_input_id=user_input.id,
    )


def _message_from_response(
    user_input: UserInput,
    response: AssistantResponse,
    *,
    include_diagnostics: bool = True,
) -> ConversationMessage:
    return ConversationMessage(
        id=response.id,
        role="assistant",
        content=response.content,
        created_at=response.created_at,
        user_input_id=user_input.id,
        response_id=response.id,
        route=_route_from_payload(response.route_payload),
        sources=_sources_from_payload(response.sources_payload),
        diagnostics=(response.diagnostics_payload or {}) if include_diagnostics else None,
    )


def _conversation_messages(conversation: Conversation, *, include_diagnostics: bool = True) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []
    for user_input in conversation.user_inputs:
        messages.append(_message_from_user_input(user_input))
        if user_input.response is not None:
            messages.append(
                _message_from_response(
                    user_input,
                    user_input.response,
                    include_diagnostics=include_diagnostics,
                )
            )
    return messages


def _conversation_message_count(conversation: Conversation) -> int:
    return sum(1 + int(user_input.response is not None) for user_input in conversation.user_inputs)


def _conversation_summary(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        is_public=conversation.is_public,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=_conversation_message_count(conversation),
    )


def _conversation_detail(conversation: Conversation, *, include_diagnostics: bool = True) -> ConversationDetail:
    messages = _conversation_messages(conversation, include_diagnostics=include_diagnostics)
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        is_public=conversation.is_public,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(messages),
        messages=messages,
    )


def _history_for_service(conversation: Conversation) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in _conversation_messages(conversation):
        history.append({"role": message.role, "content": message.content})
    return history


def _upstream_error_detail(exc: Exception) -> str:
    if isinstance(exc, requests.RequestException):
        response = getattr(exc, "response", None)
        if response is not None:
            body = str(response.text or "").strip()
            if body:
                return body[:500]
        return str(exc)

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)[:500]
    return str(exc)[:500]


def _raise_chat_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, requests.RequestException):
        detail = _upstream_error_detail(exc)
        raise HTTPException(status_code=502, detail=f"Lỗi từ dịch vụ AI phía sau: {detail}") from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Không thể tạo phản hồi lúc này. Hãy thử lại sau.",
    ) from exc


def _run_chat(user_message: str, history: list[dict[str, str]]) -> dict[str, Any]:
    try:
        return service.chat(user_message, history=history)
    except Exception as exc:  # noqa: BLE001
        _raise_chat_http_error(exc)


def _store_message_response(
    db: Session,
    conversation: Conversation,
    user_message: str,
    result: dict[str, Any],
) -> MessageResponse:
    if not conversation.user_inputs:
        conversation.title = _derive_title(user_message)
    conversation.updated_at = _utcnow()

    # Link via ORM relationships so the in-session conversation stays in sync.
    user_input = UserInput(conversation=conversation, content=user_message)
    db.add(user_input)
    db.flush()

    assistant_response = AssistantResponse(
        user_input=user_input,
        content=str(result["answer"]).strip(),
        route_payload=result["route"],
        sources_payload=result["sources"],
        diagnostics_payload=result["diagnostics"],
    )
    db.add(assistant_response)
    db.commit()

    created_input = user_input
    created_response = user_input.response
    if created_response is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Phản hồi của trợ lý chưa được lưu.")

    return MessageResponse(
        conversation=_conversation_summary(conversation),
        user_message=_message_from_user_input(created_input),
        assistant_message=_message_from_response(created_input, created_response),
        route=RouteDebug.model_validate(result["route"]),
        sources=[SourceSection.model_validate(item) for item in result["sources"]],
        diagnostics=result["diagnostics"],
    )


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config/public")
def get_public_config() -> dict[str, Any]:
    return {
        "clerkPublishableKey": settings.clerk_publishable_key,
        "clerkEnabled": bool(settings.clerk_publishable_key and clerk_verifier.is_enabled()),
        "allowedOrigins": list(settings.clerk_allowed_origins),
    }


@app.get("/api/nearby-services", response_model=NearbyServicesResponse)
def nearby_services(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    category: str = Query("all"),
    radius_m: int = Query(5000, ge=500, le=15000),
    limit: int = Query(30, ge=1, le=50),
) -> NearbyServicesResponse:
    try:
        results = fetch_nearby_services(lat=lat, lng=lng, category=category, radius_m=radius_m, limit=limit)
    except requests.RequestException as exc:
        detail = _upstream_error_detail(exc)
        raise HTTPException(status_code=502, detail=f"Không đọc được dữ liệu OpenStreetMap/Overpass: {detail}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Dữ liệu địa điểm trả về không hợp lệ: {exc}") from exc

    return NearbyServicesResponse(
        query_latitude=lat,
        query_longitude=lng,
        category=category,
        radius_m=radius_m,
        source="OpenStreetMap Overpass API",
        results=results,
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    _require_auth(request)
    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=422, detail="Tin nhắn không được để trống.")

    history = [{"role": turn.role, "content": turn.content.strip()} for turn in payload.history if turn.content.strip()]

    result = _run_chat(user_message, history)

    return ChatResponse(
        answer=result["answer"],
        user_query=user_message,
        route=result["route"],
        sources=result["sources"],
        diagnostics=result["diagnostics"],
    )


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations(request: Request, db: Session = Depends(get_db)) -> list[ConversationSummary]:
    auth = _require_auth(request)
    user = _get_or_create_user(db, auth)

    conversations = list(
        db.scalars(
            _conversation_query()
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
        )
    )
    return [_conversation_summary(conversation) for conversation in conversations]


@app.post("/api/conversations", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: CreateConversationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConversationSummary:
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Hãy gửi tin nhắn đầu tiên tới /api/messages để tạo cuộc trò chuyện.",
    )


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, request: Request, db: Session = Depends(get_db)) -> ConversationDetail:
    auth = _optional_auth(request)
    conversation = _load_conversation(db, conversation_id)
    include_diagnostics = _ensure_view_access(conversation, auth, db)
    return _conversation_detail(conversation, include_diagnostics=include_diagnostics)


@app.post("/api/message/{conversation_id}", response_model=MessageResponse)
@app.post("/api/messages/{conversation_id}", response_model=MessageResponse)
def post_message(
    conversation_id: str,
    payload: MessageRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    auth = _require_auth(request)
    user = _get_or_create_user(db, auth)
    conversation = _load_conversation(db, conversation_id)
    _ensure_owner(conversation, user)

    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tin nhắn không được để trống.")

    history = _history_for_service(conversation)
    result = _run_chat(user_message, history)

    return _store_message_response(db, conversation, user_message, result)


@app.post("/api/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def create_conversation_with_message(
    payload: MessageRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    auth = _require_auth(request)
    user = _get_or_create_user(db, auth)

    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tin nhắn không được để trống.")

    result = _run_chat(user_message, history=[])
    conversation = Conversation(user_id=user.id, title=_derive_title(user_message))
    db.add(conversation)
    db.flush()

    return _store_message_response(db, conversation, user_message, result)


@app.put("/api/conversations/{conversation_id}", response_model=ConversationSummary)
def update_conversation(
    conversation_id: str,
    payload: UpdateConversationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConversationSummary:
    auth = _require_auth(request)
    user = _get_or_create_user(db, auth)
    conversation = _load_conversation(db, conversation_id)
    _ensure_owner(conversation, user)

    conversation.is_public = payload.is_public
    conversation.updated_at = _utcnow()
    db.commit()
    db.refresh(conversation)
    return _conversation_summary(conversation)


@app.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    auth = _require_auth(request)
    user = _get_or_create_user(db, auth)
    conversation = _load_conversation(db, conversation_id)
    _ensure_owner(conversation, user)

    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _frontend_index_path() -> Path:
    return settings.frontend_dist_dir / "index.html"


def _serve_frontend_file(path: str) -> FileResponse | None:
    if not _frontend_index_path().exists():
        return None

    candidate = (settings.frontend_dist_dir / path).resolve()
    frontend_root = settings.frontend_dist_dir.resolve()
    if frontend_root in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    return None


@app.get("/", include_in_schema=False)
def serve_frontend_root() -> Response:
    if _frontend_index_path().exists():
        return FileResponse(_frontend_index_path())
    return PlainTextResponse(
        "Không tìm thấy bản build frontend. Hãy chạy `npm install` và `npm run build` trong thư mục web_app/frontend.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str) -> Response:
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Không tìm thấy."}, status_code=status.HTTP_404_NOT_FOUND)

    asset_response = _serve_frontend_file(full_path)
    if asset_response is not None:
        return asset_response

    if _frontend_index_path().exists():
        return FileResponse(_frontend_index_path())
    return PlainTextResponse(
        "Không tìm thấy bản build frontend. Hãy chạy `npm install` và `npm run build` trong thư mục web_app/frontend.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
