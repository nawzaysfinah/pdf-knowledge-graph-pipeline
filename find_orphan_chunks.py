"""Find chunks in extractions.jsonl that contain disconnected (orphan) entities.

Usage:
    python find_orphan_chunks.py

Outputs:
    orphan_chunks.jsonl   — chunks that contain at least one orphan entity
    orphan_report.txt     — summary report
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")

EXTRACTIONS_PATH    = Path("output/extractions.jsonl")
CHUNKS_PATH         = Path("output/chunks.jsonl")
ORPHAN_CHUNKS_PATH  = Path("output/orphan_chunks.jsonl")
ORPHAN_REPORT_PATH  = Path("orphan_report.txt")


def get_orphan_names() -> set[str]:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as s:
            result = s.run("MATCH (n) WHERE NOT (n)-[]-() RETURN n.name, n.type")
            names = {row["n.name"] for row in result if row["n.name"]}
    finally:
        driver.close()
    return names


def load_chunk_texts() -> dict[str, str]:
    """Return {chunk_id: text} from chunks.jsonl."""
    texts = {}
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                texts[c["chunk_id"]] = c.get("text", "")
    return texts


def scan_extractions(orphan_names: set[str]) -> list[dict]:
    chunk_texts = load_chunk_texts()
    flagged = []
    with EXTRACTIONS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)

            chunk_entity_names = {e["name"] for e in chunk.get("entities", []) if isinstance(e, dict) and "name" in e}
            matched_orphans = chunk_entity_names & orphan_names
            if not matched_orphans:
                continue

            cid = chunk.get("chunk_id", "")
            flagged.append({
                "chunk_id":       cid,
                "doc_id":         chunk.get("doc_id", ""),
                "filename":       chunk.get("filename", ""),
                "page_num":       chunk.get("page_num", 0),
                "section_heading": chunk.get("section_heading", ""),
                "text":           chunk_texts.get(cid, ""),
                "orphan_entities": sorted(matched_orphans),
                "original_triple_count": len(chunk.get("triples", [])),
                "original_triples": chunk.get("triples", []),
                "all_entities":   chunk.get("entities", []),
            })

    return flagged


def write_report(orphan_names: set[str], flagged: list[dict]) -> None:
    zero_triple  = [c for c in flagged if c["original_triple_count"] == 0]
    some_triples = [c for c in flagged if c["original_triple_count"] > 0]

    doc_counter: Counter = Counter()
    for c in flagged:
        doc_counter[c["filename"]] += len(c["orphan_entities"])

    lines = [
        "Orphan Chunk Analysis",
        "=" * 60,
        "",
        f"  Total orphan entity names in graph : {len(orphan_names)}",
        f"  Chunks containing ≥1 orphan entity : {len(flagged)}",
        f"    of which had 0 original triples  : {len(zero_triple)}",
        f"    of which had some triples        : {len(some_triples)}",
        "",
        "Top 10 source documents by orphan entity count:",
        "-" * 60,
    ]
    for doc, count in doc_counter.most_common(10):
        lines.append(f"  {count:>5}  {doc}")

    lines += ["", "=" * 60]
    ORPHAN_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print("Querying Neo4j for disconnected nodes...")
    orphan_names = get_orphan_names()
    print(f"  Found {len(orphan_names)} orphan entity names")

    print("Scanning extractions.jsonl...")
    flagged = scan_extractions(orphan_names)
    print(f"  Found {len(flagged)} chunks containing orphan entities")

    zero  = sum(1 for c in flagged if c["original_triple_count"] == 0)
    some  = len(flagged) - zero
    print(f"    {zero} chunks with 0 original triples")
    print(f"    {some} chunks with some original triples (triples were filtered out)")

    ORPHAN_CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ORPHAN_CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for chunk in flagged:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    print(f"\n  Saved → {ORPHAN_CHUNKS_PATH}")

    write_report(orphan_names, flagged)
    print(f"  Report → {ORPHAN_REPORT_PATH}")


if __name__ == "__main__":
    main()
