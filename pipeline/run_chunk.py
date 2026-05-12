"""CLI runner for Stage 3: Chunking.

Usage:
    python -m pipeline.run_chunk
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from pipeline.chunker import chunk_all

load_dotenv()

EXTRACTIONS_DIR = Path("output") / "extractions"
CHUNKS_PATH = Path("output") / "chunks.jsonl"


def main() -> None:
    print(f"\nChunking extractions in {EXTRACTIONS_DIR}/ → {CHUNKS_PATH}\n")

    new_chunks = chunk_all(EXTRACTIONS_DIR, CHUNKS_PATH)

    if not new_chunks:
        print("\n  Nothing new to chunk.")
        return

    # Summary stats
    by_type = Counter(c["content_type"] for c in new_chunks)
    headings_seen = {c["section_heading"] for c in new_chunks if c["section_heading"]}

    print(f"\n── Chunking Summary ─────────────────────────────────")
    print(f"  New chunks written : {len(new_chunks)}")
    print(f"    text             : {by_type.get('text', 0)}")
    print(f"    table            : {by_type.get('table', 0)}")
    print(f"  Unique sections    : {len(headings_seen)}")

    # Show a sample chunk
    sample = next((c for c in new_chunks if c["content_type"] == "text"), None)
    if sample:
        print(f"\n── Sample chunk (chunk_id={sample['chunk_id']}) ──────────")
        print(f"  doc_id          : {sample['doc_id']}")
        print(f"  page_num        : {sample['page_num']}")
        print(f"  section_heading : {sample['section_heading'] or '(none)'}")
        preview = sample["text"][:200].replace("\n", " ")
        print(f"  text preview    : {preview}{'…' if len(sample['text']) > 200 else ''}")

    print(f"\n  Output: {CHUNKS_PATH.resolve()}")


if __name__ == "__main__":
    main()
