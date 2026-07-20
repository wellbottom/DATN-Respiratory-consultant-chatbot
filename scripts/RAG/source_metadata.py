from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceUrlResolution:
    source_url: str | None
    source_url_kind: str | None


class SourceUrlResolver:
    def resolve(
        self,
        *,
        source_path: str | None = None,
        title: str | None = None,
        existing_url: str | None = None,
        existing_url_kind: str | None = None,
    ) -> SourceUrlResolution:
        if existing_url:
            return SourceUrlResolution(str(existing_url), existing_url_kind or "existing")
        if source_path and str(source_path).startswith(("http://", "https://")):
            return SourceUrlResolution(str(source_path), existing_url_kind or "source_path")
        return SourceUrlResolution(None, None)
