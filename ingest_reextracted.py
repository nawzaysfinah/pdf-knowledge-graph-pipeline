"""Ingest reextracted_triples.jsonl into Neo4j.

- Uses MERGE for nodes and relationships (never CREATE)
- Tags every new relationship with source='reextraction_pass'
- Never modifies existing nodes or relationships
- Prints before/after disconnected node counts

Usage:
    python ingest_reextracted.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")

INPUT_PATH = Path("output/reextracted_triples.jsonl")

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]")


def _safe_label(t: str) -> str:
    label = _SAFE_RE.sub("_", t)
    return ("T_" + label if label and label[0].isdigit() else label) or "Unknown"


def _safe_rel(pred: str) -> str:
    r = _SAFE_RE.sub("_", pred).upper()
    return ("REL_" + r if r and r[0].isdigit() else r) or "RELATED_TO"


def _node_id(name: str, etype: str) -> str:
    return f"{etype.lower()}_{hashlib.md5(name.lower().encode()).hexdigest()[:8]}"


def count_disconnected(session) -> int:
    return session.run("MATCH (n) WHERE NOT (n)-[]-() RETURN count(n) AS c").single()["c"]


def ingest(triples: list[dict], driver) -> int:
    merged = 0
    with driver.session() as session:
        for t in triples:
            subj      = t["subject"]
            obj       = t["object"]
            s_type    = t["subject_type"]
            o_type    = t["object_type"]
            predicate = t["predicate"]

            s_id = t.get("subject_canonical_id") or _node_id(subj, s_type)
            o_id = t.get("object_canonical_id")  or _node_id(obj,  o_type)

            s_label = _safe_label(s_type)
            o_label = _safe_label(o_type)
            rel_type = _safe_rel(predicate)

            # Step 1: MERGE subject node (on :Entity only to avoid label conflicts)
            session.run(
                "MERGE (n:Entity {canonical_id: $cid}) "
                "ON CREATE SET n.name = $name, n.type = $type, n.aliases = []",
                cid=s_id, name=subj, type=s_type,
            )

            # Step 2: MERGE object node
            session.run(
                "MERGE (n:Entity {canonical_id: $cid}) "
                "ON CREATE SET n.name = $name, n.type = $type, n.aliases = []",
                cid=o_id, name=obj, type=o_type,
            )

            # Step 3: MATCH both, MERGE relationship
            session.run(
                f"MATCH (s:Entity {{canonical_id: $s_cid}}) "
                f"MATCH (o:Entity {{canonical_id: $o_cid}}) "
                f"MERGE (s)-[r:{rel_type}]->(o) "
                f"ON CREATE SET "
                f"  r.predicate   = $predicate, "
                f"  r.confidence  = $confidence, "
                f"  r.evidence    = $evidence, "
                f"  r.source_doc  = $source_doc, "
                f"  r.source_page = $source_page, "
                f"  r.chunk_id    = $chunk_id, "
                f"  r.source      = 'reextraction_pass'",
                s_cid      = s_id,
                o_cid      = o_id,
                predicate  = predicate,
                confidence = float(t.get("confidence", 0.0)),
                evidence   = t.get("evidence", ""),
                source_doc = t.get("filename", ""),
                source_page= int(t.get("page_num", 0)),
                chunk_id   = t.get("chunk_id", ""),
            )
            merged += 1

    return merged


def main() -> None:
    triples = []
    with INPUT_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                triples.append(json.loads(line))

    logger.info("Loaded %d triples from %s", len(triples), INPUT_PATH)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as s:
            before = count_disconnected(s)
        logger.info("Disconnected nodes BEFORE ingest: %d", before)

        merged = ingest(triples, driver)
        logger.info("Merged %d relationships", merged)

        with driver.session() as s:
            after       = count_disconnected(s)
            total_nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            total_rels  = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        print(f"\n── Ingest Summary ─────────────────────────────────")
        print(f"  Relationships merged        : {merged}")
        print(f"  Total nodes                 : {total_nodes}")
        print(f"  Total relationships         : {total_rels}")
        print(f"  Disconnected nodes BEFORE   : {before}")
        print(f"  Disconnected nodes AFTER    : {after}")
        print(f"  Nodes connected this pass   : {before - after}")

        print(f"\n── New relationship types (reextraction_pass) ─────")
        with driver.session() as s:
            rows = s.run(
                "MATCH ()-[r]->() WHERE r.source = 'reextraction_pass' "
                "RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC"
            )
            for row in rows:
                print(f"  {row['rel']:<30} {row['cnt']}")

        print(f"\n── Sample new triples ─────────────────────────────")
        with driver.session() as s:
            rows = s.run(
                "MATCH (a)-[r]->(b) WHERE r.source = 'reextraction_pass' "
                "RETURN a.name, type(r), b.name, r.confidence LIMIT 20"
            )
            for row in rows:
                print(f"  {row['a.name']} --{row['type(r)']}--> {row['b.name']}  ({row['r.confidence']:.2f})")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
