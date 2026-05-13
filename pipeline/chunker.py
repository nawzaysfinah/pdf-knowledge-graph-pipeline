"""Stage 3: Chunking Module.

Splits extraction JSON content items into semantically coherent chunks:
  - Text items  → split at markdown headings, then paragraphs; 1-2 sentence overlap
  - Table items → always emitted as single atomic chunks

Short consecutive text chunks (< MIN_CHUNK_CHARS) are merged so the LLM
always has enough context to extract meaningful entities and relationships.

Every chunk carries provenance:
  {chunk_id, chunk_index, doc_id, filename, page_num,
   section_heading, content_type}

Output: output/chunks.jsonl  (one JSON object per line)
Re-run safe: docs already present in chunks.jsonl are skipped.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Generator

# Matches markdown headings: # Heading, ## Heading, etc.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)

# Consecutive short text chunks below this size are merged together
MIN_CHUNK_CHARS = 300

# Sentence boundary: ends with . ! ? followed by whitespace or end-of-string.
# Keeps the terminal punctuation with the sentence.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Low-level text utilities
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _trailing_sentences(text: str, n: int = 2) -> str:
    """Return the last n sentences of text (for overlap prefix)."""
    sentences = _split_sentences(text)
    return " ".join(sentences[-n:]) if sentences else ""


def _parse_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown text into (heading, body) pairs.

    Text before the first heading is yielded with heading="".
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())]

    sections: list[tuple[str, str]] = []

    # Text before the first heading
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        sections.append((heading, body))

    return sections


def _paragraphs(body: str) -> list[str]:
    """Split a section body into non-empty paragraphs."""
    return [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]


# ---------------------------------------------------------------------------
# Chunk generation
# ---------------------------------------------------------------------------

def _chunk_id(doc_id: str, index: int) -> str:
    raw = f"{doc_id}:{index}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _chunks_from_text_item(
    item: dict[str, Any],
    start_index: int,
) -> list[dict[str, Any]]:
    """Yield chunks from a single text content item."""
    chunks: list[dict[str, Any]] = []
    doc_id: str = item["doc_id"]
    overlap_prefix: str = ""
    chunk_index = start_index

    sections = _parse_markdown_sections(item["text"])

    for heading, body in sections:
        paragraphs = _paragraphs(body)

        for para_idx, paragraph in enumerate(paragraphs):
            # Prepend overlap from the previous paragraph
            if overlap_prefix and para_idx > 0:
                text = overlap_prefix + " " + paragraph
            elif overlap_prefix and chunk_index > start_index:
                # overlap from a different section
                text = overlap_prefix + " " + paragraph
            else:
                text = paragraph

            chunks.append({
                "chunk_id": _chunk_id(doc_id, chunk_index),
                "chunk_index": chunk_index,
                "doc_id": doc_id,
                "filename": item["filename"],
                "page_num": item["page_num"],
                "section_heading": heading,
                "content_type": "text",
                "text": text,
            })

            overlap_prefix = _trailing_sentences(paragraph, n=2)
            chunk_index += 1

    return chunks


def _chunk_from_table_item(
    item: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """Wrap a table item as a single atomic chunk."""
    return {
        "chunk_id": _chunk_id(item["doc_id"], index),
        "chunk_index": index,
        "doc_id": item["doc_id"],
        "filename": item["filename"],
        "page_num": item["page_num"],
        "section_heading": "",
        "content_type": "table",
        "text": item["text"],
        "raw_table": item.get("raw_table"),
    }


# ---------------------------------------------------------------------------
# Short-chunk merger (Fix A)
# ---------------------------------------------------------------------------

def _merge_short_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive short text chunks into their successor.

    Walks forward through the list. If the last emitted text chunk is still
    below MIN_CHUNK_CHARS, the next text chunk is appended to it rather than
    starting a new chunk. Tables are always kept atomic and never merged.
    Chunk IDs and indices are re-assigned after merging.
    """
    result: list[dict[str, Any]] = []

    for chunk in chunks:
        if (
            chunk["content_type"] == "text"
            and result
            and result[-1]["content_type"] == "text"
            and len(result[-1]["text"]) < MIN_CHUNK_CHARS
        ):
            # Grow the previous chunk instead of starting a new one
            result[-1]["text"] += "\n\n" + chunk["text"]
        else:
            result.append(dict(chunk))

    # Re-assign stable IDs after merging
    for idx, c in enumerate(result):
        c["chunk_index"] = idx
        c["chunk_id"] = _chunk_id(c["doc_id"], idx)

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def chunk_extraction(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a single PDF extraction dict into a list of chunks."""
    all_chunks: list[dict[str, Any]] = []
    index = 0

    for item in extraction.get("content", []):
        if item["content_type"] == "table":
            all_chunks.append(_chunk_from_table_item(item, index))
            index += 1
        elif item["content_type"] == "text":
            new_chunks = _chunks_from_text_item(item, start_index=index)
            all_chunks.extend(new_chunks)
            index += len(new_chunks)

    # Merge short text fragments so every chunk has enough context for the LLM
    return _merge_short_chunks(all_chunks)


def chunk_all(extractions_dir: Path, output_path: Path) -> list[dict[str, Any]]:
    """Chunk all extraction JSONs in extractions_dir.

    Appends to output_path (JSONL). Already-present doc_ids are skipped.
    Returns a list of all newly written chunks.
    """
    extractions_dir = Path(extractions_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load already-processed doc_ids to enable re-run safety
    processed_doc_ids: set[str] = set()
    if output_path.exists():
        with output_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        processed_doc_ids.add(json.loads(line)["doc_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass

    new_chunks: list[dict[str, Any]] = []

    extraction_files = sorted(extractions_dir.glob("*.json"))
    if not extraction_files:
        print(f"  No extraction files found in {extractions_dir}")
        return []

    with output_path.open("a", encoding="utf-8") as out:
        for ex_file in extraction_files:
            extraction = json.loads(ex_file.read_text())
            doc_id = extraction["doc_id"]

            if doc_id in processed_doc_ids:
                print(f"  SKIP  {extraction['filename']}  (already chunked)")
                continue

            chunks = chunk_extraction(extraction)
            for chunk in chunks:
                out.write(json.dumps(chunk, ensure_ascii=False) + "\n")

            new_chunks.extend(chunks)
            print(
                f"  CHUNK {extraction['filename']:<35}"
                f"  chunks={len(chunks)}"
                f"  tables={sum(1 for c in chunks if c['content_type'] == 'table')}"
            )

    return new_chunks
