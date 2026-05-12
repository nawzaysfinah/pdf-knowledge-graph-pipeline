"""Stage 8: Neo4j Ingestion.

Reads output/validated_triples.jsonl and output/canonical_map.json.
Writes an idempotent knowledge graph to Neo4j using MERGE.

Node model:
    (:Entity:<EntityType> {
        canonical_id, name, type, aliases: [str]
    })

Relationship model:
    (subject)-[:<predicate> {
        confidence, evidence, source_doc, source_page,
        chunk_id, ontology_valid, violation
    }]->(object)

Indexes created:
    :Entity(canonical_id)  — unique constraint (merge key)
    :Entity(name)          — fast name lookup
    :Entity(type)          — type-based filtering
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)

VALIDATED_PATH     = Path("output") / "validated_triples.jsonl"
CANONICAL_MAP_PATH = Path("output") / "canonical_map.json"

_SAFE_REL_RE = re.compile(r"[^a-zA-Z0-9_]")


def _safe_rel_type(predicate: str) -> str:
    """Convert predicate to a valid Neo4j relationship type identifier."""
    return _SAFE_REL_RE.sub("_", predicate).upper()


# ---------------------------------------------------------------------------
# Schema setup
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS = [
    # Unique constraint on canonical_id (also creates an index)
    "CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE",
    # Additional lookup indexes
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (n:Entity) ON (n.type)",
]


def setup_schema(driver: Driver) -> None:
    with driver.session() as session:
        for stmt in _SCHEMA_STATEMENTS:
            session.run(stmt)
    logger.info("Schema / indexes applied")


# ---------------------------------------------------------------------------
# Node collection — build canonical node registry from triples + map
# ---------------------------------------------------------------------------

def _build_node_registry(
    triples: list[dict[str, Any]],
    canonical_map: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return {canonical_id: {name, type, aliases: set}} for all entities in triples."""
    registry: dict[str, dict[str, Any]] = {}

    # Seed from canonical_map so we capture all known aliases
    for surface, entry in canonical_map.items():
        cid = entry["canonical_id"]
        if cid not in registry:
            registry[cid] = {
                "canonical_id": cid,
                "name":         entry["canonical_name"],
                "type":         entry["type"],
                "aliases":      set(),
            }
        # Every surface form that isn't the canonical name is an alias
        if surface != entry["canonical_name"]:
            registry[cid]["aliases"].add(surface)

    # Also register any entities in triples that aren't in canonical_map
    for t in triples:
        for side in ("subject", "object"):
            cid  = t.get(f"{side}_canonical_id")
            name = t[side]
            etype = t[f"{side}_type"]
            if not cid:
                # Generate a fallback id for entities that bypassed resolution
                import hashlib
                cid = f"{etype.lower()}_{hashlib.md5(name.lower().encode()).hexdigest()[:8]}"
            if cid not in registry:
                registry[cid] = {
                    "canonical_id": cid,
                    "name":         name,
                    "type":         etype,
                    "aliases":      set(),
                }

    return registry


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _ingest_nodes(session: Any, registry: dict[str, dict[str, Any]]) -> int:
    count = 0
    for node in registry.values():
        entity_type = node["type"]
        aliases     = sorted(node["aliases"])
        # Bake the specific type label into the query (safe: comes from controlled ontology vocab)
        cypher = (
            f"MERGE (n:Entity:{entity_type} {{canonical_id: $cid}}) "
            f"SET n.name = $name, n.type = $type, n.aliases = $aliases"
        )
        session.run(
            cypher,
            cid=node["canonical_id"],
            name=node["name"],
            type=entity_type,
            aliases=aliases,
        )
        count += 1
    return count


def _ingest_relationships(session: Any, triples: list[dict[str, Any]]) -> int:
    count = 0
    for t in triples:
        subj_cid = t.get("subject_canonical_id") or \
            f"{t['subject_type'].lower()}_{__import__('hashlib').md5(t['subject'].lower().encode()).hexdigest()[:8]}"
        obj_cid  = t.get("object_canonical_id") or \
            f"{t['object_type'].lower()}_{__import__('hashlib').md5(t['object'].lower().encode()).hexdigest()[:8]}"

        rel_type = _safe_rel_type(t["predicate"])

        cypher = (
            f"MATCH (s:Entity {{canonical_id: $s_cid}}) "
            f"MATCH (o:Entity {{canonical_id: $o_cid}}) "
            f"MERGE (s)-[r:{rel_type}]->(o) "
            f"SET r.predicate      = $predicate, "
            f"    r.confidence     = $confidence, "
            f"    r.evidence       = $evidence, "
            f"    r.source_doc     = $source_doc, "
            f"    r.source_page    = $source_page, "
            f"    r.chunk_id       = $chunk_id, "
            f"    r.ontology_valid = $ontology_valid, "
            f"    r.violation      = $violation"
        )
        session.run(
            cypher,
            s_cid        = subj_cid,
            o_cid        = obj_cid,
            predicate    = t["predicate"],
            confidence   = float(t.get("confidence", 0.0)),
            evidence     = t.get("evidence", ""),
            source_doc   = t.get("filename", ""),
            source_page  = int(t.get("page_num", 0)),
            chunk_id     = t.get("chunk_id", ""),
            ontology_valid = bool(t.get("ontology_valid", False)),
            violation    = t.get("violation") or "",
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Summary queries
# ---------------------------------------------------------------------------

def print_summary(driver: Driver) -> None:
    with driver.session() as session:
        total_nodes = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
        total_rels  = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        print(f"\n── Neo4j Ingestion Summary ─────────────────────────────")
        print(f"  Total nodes         : {total_nodes}")
        print(f"  Total relationships : {total_rels}")

        print(f"\n  Nodes by type:")
        rows = session.run(
            "MATCH (n:Entity) RETURN n.type AS type, count(n) AS cnt ORDER BY cnt DESC"
        )
        for row in rows:
            print(f"    {row['type']:<28} {row['cnt']}")

        print(f"\n  Relationships by type:")
        rows = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC"
        )
        for row in rows:
            print(f"    {row['rel']:<28} {row['cnt']}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    validated_path: Path = VALIDATED_PATH,
    canonical_map_path: Path = CANONICAL_MAP_PATH,
) -> None:
    # Load inputs
    triples: list[dict[str, Any]] = []
    with validated_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                triples.append(json.loads(line))

    canonical_map: dict[str, Any] = json.loads(canonical_map_path.read_text())

    logger.info("Loaded %d triples and %d canonical entries", len(triples), len(canonical_map))

    registry = _build_node_registry(triples, canonical_map)
    logger.info("Node registry: %d canonical entities", len(registry))

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        setup_schema(driver)

        with driver.session() as session:
            node_count = _ingest_nodes(session, registry)
            logger.info("Merged %d nodes", node_count)

            rel_count = _ingest_relationships(session, triples)
            logger.info("Merged %d relationships", rel_count)

        print_summary(driver)
    finally:
        driver.close()
