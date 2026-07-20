from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError

from .settings import AppSettings


@dataclass(slots=True)
class AuthenticatedRequest:
    clerk_user_id: str
    session_id: str | None
    claims: dict[str, Any]


def _normalize_public_key(raw_key: str) -> str:
    return raw_key.replace("\\n", "\n").strip()


def _is_inline_verify_key(raw_key: str) -> bool:
    normalized = _normalize_public_key(raw_key)
    if not normalized:
        return False
    if normalized.startswith("{"):
        return True
    if "BEGIN PUBLIC KEY" in normalized or "BEGIN RSA PUBLIC KEY" in normalized:
        return True
    return False


def _normalize_origin(origin: str) -> str:
    raw = origin.strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/").lower()

    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "", "", "")).rstrip("/")


class ClerkTokenVerifier:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.allowed_origins = {
            normalized
            for normalized in (_normalize_origin(origin) for origin in settings.clerk_allowed_origins)
            if normalized
        }
        self.allow_any_origin = "*" in self.allowed_origins
        self.issuer = settings.clerk_frontend_api_url.rstrip("/") if settings.clerk_frontend_api_url else None
        self.jwt_key = self._resolve_inline_jwt_key()
        self.jwks_url = self._resolve_jwks_url()
        self._jwk_client = jwt.PyJWKClient(self.jwks_url) if self.jwks_url else None

    def _resolve_inline_jwt_key(self) -> str | None:
        raw_key = self.settings.clerk_jwt_key
        if not raw_key:
            return None

        normalized = _normalize_public_key(raw_key)
        if _is_inline_verify_key(normalized):
            return normalized

        return None

    def _resolve_jwks_url(self) -> str | None:
        if self.settings.clerk_jwks_url:
            return self.settings.clerk_jwks_url.strip()
        if self.settings.clerk_frontend_api_url:
            return f"{self.settings.clerk_frontend_api_url.rstrip('/')}/.well-known/jwks.json"
        return None

    def is_enabled(self) -> bool:
        return bool(self.jwt_key or self._jwk_client)

    def _is_authorized_party_allowed(self, authorized_party: str) -> bool:
        if self.allow_any_origin:
            return True
        normalized = _normalize_origin(authorized_party)
        return not normalized or not self.allowed_origins or normalized in self.allowed_origins

    def _extract_token(self, request: Request) -> str | None:
        authorization = request.headers.get("Authorization", "").strip()
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            if token:
                return token

        session_cookie = request.cookies.get("__session")
        if session_cookie:
            return session_cookie.strip()
        return None

    def _signing_key_for(self, token: str) -> Any:
        if self.jwt_key:
            if self.jwt_key.startswith("{"):
                return jwt.algorithms.RSAAlgorithm.from_jwk(self.jwt_key)
            return self.jwt_key
        if self._jwk_client is None:
            raise RuntimeError(
                "Clerk chưa được cấu hình xác thực. Hãy đặt CLERK_JWT_KEY hoặc CLERK_FRONTEND_API_URL/CLERK_JWKS_URL."
            )
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def verify_request(self, request: Request) -> AuthenticatedRequest | None:
        token = self._extract_token(request)
        if not token:
            return None
        return self.verify_token(token)

    def verify_token(self, token: str) -> AuthenticatedRequest:
        try:
            claims = jwt.decode(
                token,
                self._signing_key_for(token),
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"require": ["exp", "iat", "nbf", "sub"]},
            )
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên đăng nhập Clerk không hợp lệ.") from exc

        authorized_party = claims.get("azp")
        normalized_authorized_party = _normalize_origin(str(authorized_party or ""))
        if not self._is_authorized_party_allowed(str(authorized_party or "")):
            allowed = ", ".join(sorted(self.allowed_origins))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Nguồn gốc được ủy quyền trong token Clerk không hợp lệ. "
                    f"Nhận được '{normalized_authorized_party}'. Các origin được phép: {allowed}."
                ),
            )

        if claims.get("sts") == "pending":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Phiên Clerk đang chờ hoàn tất thiết lập tổ chức.")

        clerk_user_id = str(claims.get("sub") or "").strip()
        if not clerk_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token Clerk không có mã người dùng.")

        return AuthenticatedRequest(
            clerk_user_id=clerk_user_id,
            session_id=str(claims.get("sid") or "").strip() or None,
            claims={str(key): value for key, value in claims.items()},
        )
