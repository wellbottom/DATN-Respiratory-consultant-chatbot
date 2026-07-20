from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from tqdm.auto import tqdm

from .common import configure_utf8_stdio, normalize_for_match, normalize_whitespace, relative_to_cwd, word_count


H1_RE = re.compile(r"^\s*#\s+(?P<text>.+?)\s*$")
H2_RE = re.compile(r"^\s*##\s+(?P<text>.+?)\s*$")
H3_RE = re.compile(r"^\s*###\s+(?P<text>.+?)\s*$")
H4_RE = re.compile(r"^\s*####\s+(?P<text>.+?)\s*$")
H5_RE = re.compile(r"^\s*#{5,}\s+(?P<text>.+?)\s*$")
LIST_MARKER_RE = re.compile(r"^\s*[-*+]\s*")
NUMBERING_RE = re.compile(r"^\s*(?:(?:\d+(?:\.\d+)*)|(?:[IVXLCDM]+))[.)]?\s+", re.IGNORECASE)
TRAILING_BRAND_RE = re.compile(r"\s*\|\s*Vinmec\s*$", re.IGNORECASE)
DEFAULT_CHUNK_TARGET_WORDS = 1000
DEFAULT_CHUNK_OVERLAP_WORDS = 200
DEFAULT_MAX_SECTION_WORDS = 1000
DEFAULT_SPLIT_H3_WHEN_SECTION_EXCEEDS = 1000
DEFAULT_MERGE_SHORT_SECTION_WORDS = 120
DEFAULT_DEDUPE_MIN_CHARS = 30


@dataclass(slots=True)
class ChunkingConfig:
    chunk_target_words: int = DEFAULT_CHUNK_TARGET_WORDS
    chunk_overlap_words: int = DEFAULT_CHUNK_OVERLAP_WORDS
    max_section_words: int = DEFAULT_MAX_SECTION_WORDS
    split_h3_when_section_exceeds: int = DEFAULT_SPLIT_H3_WHEN_SECTION_EXCEEDS
    merge_short_section_words: int = DEFAULT_MERGE_SHORT_SECTION_WORDS
    dedupe_min_chars: int = DEFAULT_DEDUPE_MIN_CHARS
    one_chunk_per_h3_section: bool = False
    h3_only: bool = False


@dataclass(slots=True)
class H5Section:
    heading: str
    body_lines: list[str] = field(default_factory=list)

    def body_text(self) -> str:
        return normalize_whitespace("\n".join(self.body_lines))


@dataclass(slots=True)
class H4Section:
    heading: str
    body_lines: list[str] = field(default_factory=list)
    children: list[H5Section] = field(default_factory=list)

    def body_text(self) -> str:
        blocks: list[str] = []
        preamble = normalize_whitespace("\n".join(self.body_lines))
        if preamble:
            blocks.append(preamble)
        for child in self.children:
            child_blocks = [f"##### {child.heading}"]
            child_body = child.body_text()
            if child_body:
                child_blocks.append(child_body)
            blocks.append("\n\n".join(child_blocks))
        return "\n\n".join(blocks).strip()


@dataclass(slots=True)
class H3Section:
    heading: str
    body_lines: list[str] = field(default_factory=list)
    children: list[H4Section] = field(default_factory=list)

    def body_text(self) -> str:
        blocks: list[str] = []
        preamble = normalize_whitespace("\n".join(self.body_lines))
        if preamble:
            blocks.append(preamble)
        for child in self.children:
            child_blocks = [f"#### {child.heading}"]
            child_body = child.body_text()
            if child_body:
                child_blocks.append(child_body)
            blocks.append("\n\n".join(child_blocks))
        return "\n\n".join(blocks).strip()


@dataclass(slots=True)
class H2Section:
    heading: str
    preamble_lines: list[str] = field(default_factory=list)
    children: list[H3Section] = field(default_factory=list)

    def full_text(self) -> str:
        blocks: list[str] = []
        preamble = normalize_whitespace("\n".join(self.preamble_lines))
        if preamble:
            blocks.append(preamble)
        for child in self.children:
            child_blocks = [f"### {child.heading}"]
            child_body = child.body_text()
            if child_body:
                child_blocks.append(child_body)
            blocks.append("\n\n".join(child_blocks))
        return "\n\n".join(blocks).strip()


@dataclass(slots=True)
class CandidateSection:
    h2: str | None
    h3: str | None
    h4: str | None
    heading_path: list[str]
    section_type: str
    content: str


def discover_default_inputs() -> list[Path]:
    defaults = [
        Path("data/vinmec_child_articles/corpus/markdown"),
        Path("data/vinmec_diseases_articles"),
    ]
    return [path for path in defaults if path.exists()]


def clean_heading(text: str) -> str:
    text = TRAILING_BRAND_RE.sub("", text or "").strip()
    return normalize_whitespace(text)


def normalize_line_for_dedupe(line: str) -> str:
    cleaned = LIST_MARKER_RE.sub("", line.strip())
    return normalize_for_match(cleaned, fold_accents=True)


def clean_markdown_document(text: str, *, dedupe_min_chars: int) -> str:
    text = text.replace("\ufeff", "")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    output: list[str] = []
    previous_norm = ""
    previous_was_blank = False

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if not previous_was_blank and output:
                output.append("")
            previous_was_blank = True
            previous_norm = ""
            continue

        current_norm = normalize_line_for_dedupe(stripped)
        if previous_norm and current_norm == previous_norm and len(stripped) >= dedupe_min_chars:
            continue

        output.append(line)
        previous_norm = current_norm
        previous_was_blank = False

    return normalize_whitespace("\n".join(output))


def combine_h1_titles(titles: list[str]) -> str:
    cleaned = [clean_heading(title) for title in titles if clean_heading(title)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if re.match(r"^BÀI\s+\d+\b", cleaned[0], re.IGNORECASE):
        return f"{cleaned[0]} - {' '.join(cleaned[1:])}"
    return normalize_whitespace(" ".join(cleaned))


def split_h1_documents(text: str, fallback_title: str) -> list[tuple[str, list[str]]]:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)

    segments: list[tuple[str, list[str]]] = []
    pending_titles: list[str] = []
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal pending_titles, body_lines
        title = combine_h1_titles(pending_titles) or clean_heading(fallback_title)
        body = list(body_lines)
        if title or body:
            segments.append((title, body))
        pending_titles = []
        body_lines = []

    for line in lines:
        match = H1_RE.match(line)
        if match:
            title = match.group("text")
            if pending_titles and not any(existing.strip() for existing in body_lines):
                pending_titles.append(title)
                continue
            if pending_titles or body_lines:
                flush()
            pending_titles = [title]
            continue
        body_lines.append(line)

    if pending_titles or body_lines:
        flush()

    return segments or [(clean_heading(fallback_title), lines)]


def parse_sections(lines: list[str]) -> tuple[str, list[H2Section]]:
    intro_lines: list[str] = []
    h2_sections: list[H2Section] = []
    current_h2: H2Section | None = None
    current_h3: H3Section | None = None
    current_h4: H4Section | None = None
    current_h5: H5Section | None = None

    def flush_h5() -> None:
        nonlocal current_h5, current_h4
        if current_h4 is not None and current_h5 is not None:
            current_h4.children.append(current_h5)
            current_h5 = None

    def flush_h4() -> None:
        nonlocal current_h4, current_h3
        if current_h3 is not None and current_h4 is not None:
            flush_h5()
            current_h3.children.append(current_h4)
            current_h4 = None

    def flush_h3() -> None:
        nonlocal current_h3, current_h2
        if current_h2 is not None and current_h3 is not None:
            flush_h4()
            current_h2.children.append(current_h3)
            current_h3 = None

    def flush_h2() -> None:
        nonlocal current_h2
        if current_h2 is not None:
            flush_h3()
            h2_sections.append(current_h2)
            current_h2 = None

    for line in lines:
        h2_match = H2_RE.match(line)
        if h2_match:
            flush_h2()
            current_h2 = H2Section(heading=clean_heading(h2_match.group("text")))
            continue

        h3_match = H3_RE.match(line)
        if h3_match and current_h2 is not None:
            flush_h3()
            current_h3 = H3Section(heading=clean_heading(h3_match.group("text")))
            continue

        h4_match = H4_RE.match(line)
        if h4_match and current_h3 is not None:
            flush_h4()
            current_h4 = H4Section(heading=clean_heading(h4_match.group("text")))
            continue

        h5_match = H5_RE.match(line)
        if h5_match and current_h4 is not None:
            flush_h5()
            current_h5 = H5Section(heading=clean_heading(h5_match.group("text")))
            continue

        if current_h5 is not None:
            current_h5.body_lines.append(line)
        elif current_h4 is not None:
            current_h4.body_lines.append(line)
        elif current_h3 is not None:
            current_h3.body_lines.append(line)
        elif current_h2 is not None:
            current_h2.preamble_lines.append(line)
        else:
            intro_lines.append(line)

    flush_h2()
    intro = normalize_whitespace("\n".join(intro_lines))
    return intro, h2_sections


def classify_section_type(
    h2: str | None,
    h3: str | None,
    h4: str | None = None,
    *,
    is_intro: bool = False,
) -> str:
    if is_intro:
        return "mở đầu"
    heading = normalize_for_match(f"{h2 or ''} {h3 or ''} {h4 or ''}", fold_accents=True)
    if not heading:
        return "nội dung"
    if "dai cuong" in heading or "tong quan" in heading:
        return "đại cương"
    if "nguyen nhan" in heading:
        return "nguyên nhân"
    if "trieu chung" in heading or "dau hieu" in heading:
        return "triệu chứng"
    if "duong lay truyen" in heading:
        return "đường lây truyền"
    if "nguy co" in heading:
        return "nguy cơ"
    if "phong ngua" in heading or "du phong" in heading:
        return "phòng ngừa"
    if "chan doan" in heading:
        return "chẩn đoán"
    if "dieu tri" in heading or "cham soc" in heading:
        return "điều trị"
    if "phan loai" in heading or "muc do" in heading:
        return "phân loại"
    if "tien luong" in heading:
        return "tiên lượng"
    if "bien chung" in heading or "theo doi" in heading or "xu tri" in heading:
        return "theo dõi/biến chứng"
    return "nội dung"


def split_long_text(text: str, config: ChunkingConfig) -> list[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    if word_count(text) < config.max_section_words:
        return [text]
    return split_text_by_word_window(text, config.chunk_target_words, config.chunk_overlap_words)


def split_text_by_word_window(text: str, target_words: int, overlap_words: int) -> list[str]:
    spans = list(re.finditer(r"\S+", text))
    if len(spans) <= target_words:
        return [text.strip()]

    windows: list[str] = []
    start = 0
    while start < len(spans):
        end = min(start + target_words, len(spans))
        chunk_text = text[spans[start].start() : spans[end - 1].end()].strip()
        if chunk_text:
            windows.append(normalize_whitespace(chunk_text))
        if end >= len(spans):
            break
        start = max(end - overlap_words, start + 1)
    return windows


def make_candidates(intro: str, h2_sections: list[H2Section], config: ChunkingConfig) -> list[CandidateSection]:
    candidates: list[CandidateSection] = []
    if intro and not config.h3_only:
        candidates.append(
            CandidateSection(
                h2=None,
                h3=None,
                h4=None,
                heading_path=[],
                section_type=classify_section_type(None, None, is_intro=True),
                content=intro,
            )
        )

    def append_candidate(
        h2: str | None,
        h3: str | None,
        h4: str | None,
        content: str,
        *,
        heading_path: list[str] | None = None,
    ) -> None:
        normalized_content = normalize_whitespace(content)
        if not normalized_content:
            return
        active_heading_path = heading_path or [heading for heading in [h2, h3, h4] if heading]
        type_headings = active_heading_path[-3:]
        while len(type_headings) < 3:
            type_headings.append(None)
        candidates.append(
            CandidateSection(
                h2=h2,
                h3=h3,
                h4=h4,
                heading_path=active_heading_path,
                section_type=classify_section_type(type_headings[0], type_headings[1], type_headings[2]),
                content=normalized_content,
            )
        )

    def h3_preamble_text(h2_preamble: str, child: H3Section, *, include_h2_preamble: bool) -> str:
        parts = []
        if include_h2_preamble and h2_preamble:
            parts.append(h2_preamble)
        child_preamble = normalize_whitespace("\n".join(child.body_lines))
        if child_preamble:
            parts.append(child_preamble)
        return normalize_whitespace("\n\n".join(parts))

    def h4_lead_in_text(h3_lead_in: str, child: H4Section, *, include_h3_lead_in: bool) -> str:
        parts = []
        if include_h3_lead_in and h3_lead_in:
            parts.append(h3_lead_in)
        h4_preamble = normalize_whitespace("\n".join(child.body_lines))
        if h4_preamble:
            parts.append(h4_preamble)
        return normalize_whitespace("\n\n".join(parts))

    for section in h2_sections:
        h2_preamble = normalize_whitespace("\n".join(section.preamble_lines))
        if not section.children:
            if not config.h3_only:
                append_candidate(section.heading, None, None, h2_preamble)
            continue

        for child_index, child in enumerate(section.children):
            h3_lead_in = h3_preamble_text(h2_preamble, child, include_h2_preamble=child_index == 0)
            if child.children:
                emitted_h4 = False
                for h4_index, grandchild in enumerate(child.children):
                    h4_lead_in = h4_lead_in_text(
                        h3_lead_in,
                        grandchild,
                        include_h3_lead_in=h4_index == 0,
                    )
                    if grandchild.children:
                        emitted_h5 = False
                        for h5_index, great_grandchild in enumerate(grandchild.children):
                            h5_content = normalize_whitespace(
                                "\n\n".join(
                                    part
                                    for part in [
                                        h4_lead_in if h5_index == 0 else "",
                                        great_grandchild.body_text(),
                                    ]
                                    if part
                                )
                            )
                            if h5_content:
                                append_candidate(
                                    section.heading,
                                    child.heading,
                                    great_grandchild.heading,
                                    h5_content,
                                    heading_path=[
                                        section.heading,
                                        child.heading,
                                        grandchild.heading,
                                        great_grandchild.heading,
                                    ],
                                )
                                emitted_h5 = True
                                emitted_h4 = True
                        if emitted_h5:
                            continue

                    h4_body = grandchild.body_text()
                    h4_content = normalize_whitespace(
                        "\n\n".join(part for part in [h3_lead_in if h4_index == 0 else "", h4_body] if part)
                    )
                    if h4_content:
                        append_candidate(section.heading, child.heading, grandchild.heading, h4_content)
                        emitted_h4 = True
                if not emitted_h4 and h3_lead_in:
                    append_candidate(section.heading, child.heading, None, h3_lead_in)
                continue

            append_candidate(section.heading, child.heading, None, h3_lead_in)

    return candidates


def build_chunk_text(title: str, candidate: CandidateSection, content: str) -> str:
    title = (title or "").strip()
    prefix_parts: list[str] = []
    if title:
        prefix_parts.append(title)
    if candidate.heading_path:
        prefix_parts.append(" > ".join(candidate.heading_path))
    prefix = " ".join(prefix_parts)
    if prefix:
        return f"{prefix}. Nội dung: {content}".strip()
    return f"Nội dung: {content}".strip()


def build_document_chunks(source_path: Path, config: ChunkingConfig) -> list[dict]:
    raw_text = source_path.read_text(encoding="utf-8", errors="replace")
    cleaned_text = clean_markdown_document(raw_text, dedupe_min_chars=config.dedupe_min_chars)
    rows: list[dict] = []
    source_file = relative_to_cwd(source_path)

    for title, body_lines in split_h1_documents(cleaned_text, source_path.stem.replace("_", " ")):
        intro, h2_sections = parse_sections(body_lines)
        candidates = make_candidates(intro, h2_sections, config)

        for candidate in candidates:
            for content in split_long_text(candidate.content, config):
                chunk_text = build_chunk_text(title, candidate, content)
                rows.append(
                    {
                        "text": chunk_text,
                        "type": candidate.section_type,
                        "source_file": source_file,
                    }
                )

    return rows


def iter_markdown_files(input_dirs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for input_dir in input_dirs:
        for path in sorted(input_dir.glob("*.md")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return files


def build_chunk_file(
    input_dirs: Iterable[Path],
    output_path: Path,
    *,
    stats_path: Path | None = None,
    config: ChunkingConfig | None = None,
    include_metadata: bool = True,
) -> dict:
    active_config = config or ChunkingConfig()
    files = iter_markdown_files(input_dirs)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document_count = 0
    chunk_count = 0
    section_type_counts: Counter[str] = Counter()

    with output_path.open("w", encoding="utf-8") as handle:
        for source_path in tqdm(files, desc="Chunking", unit="file"):
            rows = build_document_chunks(source_path, active_config)
            document_count += 1
            chunk_count += len(rows)
            for row in rows:
                section_type_counts[row["type"]] += 1
                output_row = row if include_metadata else {"text": row["text"]}
                handle.write(json.dumps(output_row, ensure_ascii=False) + "\n")

    stats = {
        "documents": document_count,
        "chunks": chunk_count,
        "avg_chunks_per_doc": round(chunk_count / max(document_count, 1), 2),
        "types": dict(section_type_counts.most_common()),
        "metadata_fields": ["type", "source_file"],
        "config": {
            "chunk_target_words": active_config.chunk_target_words,
            "chunk_overlap_words": active_config.chunk_overlap_words,
            "max_section_words": active_config.max_section_words,
            "split_h3_when_section_exceeds": active_config.split_h3_when_section_exceeds,
            "merge_short_section_words": active_config.merge_short_section_words,
            "dedupe_min_chars": active_config.dedupe_min_chars,
            "one_chunk_per_h3_section": active_config.one_chunk_per_h3_section,
            "h3_only": active_config.h3_only,
            "include_metadata": include_metadata,
        },
    }

    if stats_path is not None:
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cắt file markdown thành JSONL dùng cho truy hồi.")
    parser.add_argument(
        "--input-dir",
        action="append",
        dest="input_dirs",
        help="Markdown directory to ingest. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/chunks/local_rag.chunks.jsonl"),
        help="File JSONL đầu ra.",
    )
    parser.add_argument(
        "--stats-output",
        type=Path,
        default=Path("data/chunks/local_rag.chunks.stats.json"),
        help="File thống kê JSON đầu ra.",
    )
    parser.add_argument("--chunk-target-words", type=int, default=DEFAULT_CHUNK_TARGET_WORDS)
    parser.add_argument("--chunk-overlap-words", type=int, default=DEFAULT_CHUNK_OVERLAP_WORDS)
    parser.add_argument("--max-section-words", type=int, default=DEFAULT_MAX_SECTION_WORDS)
    parser.add_argument("--split-h3-when-section-exceeds", type=int, default=DEFAULT_SPLIT_H3_WHEN_SECTION_EXCEEDS)
    parser.add_argument("--merge-short-section-words", type=int, default=DEFAULT_MERGE_SHORT_SECTION_WORDS)
    parser.add_argument("--dedupe-min-chars", type=int, default=DEFAULT_DEDUPE_MIN_CHARS)
    parser.add_argument(
        "--one-chunk-per-h3-section",
        action="store_true",
        help="Cờ tương thích cũ; hiện tại chunking đi theo luồng H2/H3/H4.",
    )
    parser.add_argument(
        "--h3-only",
        action="store_true",
        help="Bỏ qua section chỉ có H2. Cần --one-chunk-per-h3-section để tương thích CLI.",
    )
    parser.add_argument(
        "--text-only-output",
        action="store_true",
        help="Ghi JSONL kiểu cũ, chỉ có field text.",
    )
    args = parser.parse_args()
    if args.h3_only and not args.one_chunk_per_h3_section:
        parser.error("--h3-only requires --one-chunk-per-h3-section")
    return args


def main() -> None:
    configure_utf8_stdio()
    args = parse_args()
    input_dirs = [Path(path) for path in args.input_dirs] if args.input_dirs else discover_default_inputs()
    if not input_dirs:
        raise SystemExit("Không tìm thấy thư mục đầu vào. Hãy truyền --input-dir.")

    config = ChunkingConfig(
        chunk_target_words=args.chunk_target_words,
        chunk_overlap_words=args.chunk_overlap_words,
        max_section_words=args.max_section_words,
        split_h3_when_section_exceeds=args.split_h3_when_section_exceeds,
        merge_short_section_words=args.merge_short_section_words,
        dedupe_min_chars=args.dedupe_min_chars,
        one_chunk_per_h3_section=args.one_chunk_per_h3_section,
        h3_only=args.h3_only,
    )
    stats = build_chunk_file(
        input_dirs,
        args.output,
        stats_path=args.stats_output,
        config=config,
        include_metadata=not args.text_only_output,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
