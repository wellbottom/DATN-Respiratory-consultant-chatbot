from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterator

WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")


def canonical_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", canonical_unicode(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.replace("\u0111", "d").replace("\u0110", "D")


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


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
