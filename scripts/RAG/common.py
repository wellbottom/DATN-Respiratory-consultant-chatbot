from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, Iterator, Sequence


WORD_RE = re.compile(r"[0-9A-Za-zÀ-ỹ]+", re.UNICODE)
WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")
_ENV_STATE: dict[str, Path | None | bool] = {"loaded": False, "path": None}


def canonical_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", canonical_unicode(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.replace("đ", "d").replace("Đ", "D")


def normalize_whitespace(text: str) -> str:
    text = canonical_unicode(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines).strip()
    return BLANK_LINES_RE.sub("\n\n", text)


def normalize_for_match(text: str, *, fold_accents: bool = True) -> str:
    text = normalize_whitespace(text).casefold()
    if fold_accents:
        text = strip_accents(text).casefold()
    return text


def simple_word_tokenize(text: str, *, fold_accents: bool = True) -> list[str]:
    normalized = normalize_for_match(text, fold_accents=fold_accents)
    return WORD_RE.findall(normalized)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(canonical_unicode(text)))


def stable_hash(*parts: object, length: int = 16) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(str(part).encode("utf-8", errors="ignore"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:length]


def relative_to_cwd(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def batched(items: Sequence[str], batch_size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def configure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def load_project_env(*, override: bool = False) -> Path | None:
    if _ENV_STATE["loaded"] and not override:
        return _ENV_STATE["path"]  # type: ignore[return-value]

    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        _ENV_STATE["loaded"] = True
        _ENV_STATE["path"] = None
        return None

    env_path = find_dotenv(usecwd=True)
    if not env_path:
        _ENV_STATE["loaded"] = True
        _ENV_STATE["path"] = None
        return None

    load_dotenv(env_path, override=override)
    resolved = Path(env_path).resolve()
    _ENV_STATE["loaded"] = True
    _ENV_STATE["path"] = resolved
    return resolved
