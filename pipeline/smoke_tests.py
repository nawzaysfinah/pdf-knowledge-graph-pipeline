"""Stage 9: Smoke Test Queries.

Runs three verification queries against the live Neo4j graph and
prints formatted results.

Queries:
  Q1  — Top 10 most connected entities (by total degree)
  Q2  — All relationships involving the top 3 entities by degree
  Q3  — Entity pairs that may still need manual merging
         (same type, name substring match, different canonical_id)
"""
from __future__ import annotations

import os
from typing import Any

from neo4j import Driver, GraphDatabase


# ---------------------------------------------------------------------------
# Q1: 10 most connected entities by degree
# ---------------------------------------------------------------------------

Q1 = """
MATCH (n:Entity)
WITH n,
     size([(n)-[]->(m) | m]) AS out_degree,
     size([(m)-[]->(n) | m]) AS in_degree
WITH n, out_degree, in_degree, out_degree + in_degree AS degree
ORDER BY degree DESC
LIMIT 10
RETURN n.name     AS name,
       n.type     AS type,
       out_degree AS out,
       in_degree  AS in,
       degree     AS total
"""

# ---------------------------------------------------------------------------
# Q2: All relationships for the top-3 most-connected entities
# ---------------------------------------------------------------------------

Q2_TOP3 = """
MATCH (n:Entity)
WITH n,
     size([(n)-[]->(m) | m]) + size([(m)-[]->(n) | m]) AS degree
ORDER BY degree DESC
LIMIT 3
RETURN n.name AS name
"""

Q2_RELS = """
MATCH (n:Entity {name: $name})-[r]-(other:Entity)
RETURN
    n.name          AS entity,
    n.type          AS entity_type,
    CASE WHEN startNode(r) = n THEN '→' ELSE '←' END AS direction,
    type(r)         AS predicate,
    other.name      AS related,
    other.type      AS related_type,
    r.confidence    AS confidence,
    r.evidence      AS evidence,
    r.ontology_valid AS ontology_valid
ORDER BY predicate, related
"""

# ---------------------------------------------------------------------------
# Q3: Possible surviving duplicates (same type, name contains other's name)
# ---------------------------------------------------------------------------

Q3 = """
MATCH (a:Entity), (b:Entity)
WHERE a.type = b.type
  AND elementId(a) < elementId(b)
  AND a.canonical_id <> b.canonical_id
  AND (toLower(a.name) CONTAINS toLower(b.name)
       OR toLower(b.name) CONTAINS toLower(a.name))
RETURN a.name AS name_a,
       b.name AS name_b,
       a.type AS type
ORDER BY a.type, a.name
LIMIT 20
"""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _header(title: str) -> None:
    print(f"\n{'─' * 64}")
    print(f"  {title}")
    print(f"{'─' * 64}")


def _run_q1(driver: Driver) -> list[str]:
    _header("Q1 — Top 10 Most Connected Entities (by degree)")
    top_names: list[str] = []
    with driver.session() as session:
        rows = list(session.run(Q1))
    if not rows:
        print("  (no entities found)")
        return []
    print(f"  {'#':<4} {'Name':<35} {'Type':<25} {'Out':>4} {'In':>4} {'Total':>6}")
    print(f"  {'-'*4} {'-'*35} {'-'*25} {'-'*4} {'-'*4} {'-'*6}")
    for i, row in enumerate(rows, 1):
        print(
            f"  {i:<4} {row['name']:<35} {row['type']:<25}"
            f" {row['out']:>4} {row['in']:>4} {row['total']:>6}"
        )
        if i <= 3:
            top_names.append(row["name"])
    return top_names


def _run_q2(driver: Driver, top_names: list[str]) -> None:
    _header(f"Q2 — All Relationships for Top {len(top_names)} Entity/Entities")
    if not top_names:
        print("  (no top entities — skipping)")
        return

    # Fallback: if Q1 returned nothing, query top-3 directly
    if not top_names:
        with driver.session() as s:
            rows = list(s.run(Q2_TOP3))
        top_names = [r["name"] for r in rows]

    with driver.session() as session:
        for name in top_names:
            rows = list(session.run(Q2_RELS, name=name))
            print(f"\n  Entity: {name!r}")
            if not rows:
                print("    (no relationships)")
                continue
            for r in rows:
                valid_mark = "✓" if r["ontology_valid"] else "✗"
                ev = (r["evidence"] or "")[:60]
                print(
                    f"    {valid_mark} {r['direction']} [{r['predicate']}]"
                    f"  {r['related']!r} ({r['related_type']})"
                    f"  conf={r['confidence']:.2f}"
                )
                if ev:
                    print(f"       evidence: {ev!r}")


def _run_q3(driver: Driver) -> None:
    _header("Q3 — Possible Surviving Duplicate Entities (manual review)")
    with driver.session() as session:
        rows = list(session.run(Q3))
    if not rows:
        print("  ✓ No near-duplicate pairs detected.")
        return
    print(f"  {'Type':<25} {'Name A':<35} {'Name B'}")
    print(f"  {'-'*25} {'-'*35} {'-'*30}")
    for row in rows:
        print(f"  {row['type']:<25} {row['name_a']:<35} {row['name_b']}")
    print(f"\n  {len(rows)} pair(s) flagged. "
          f"Consider updating canonical_map.json and re-running Stage 7 + 8.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_smoke_tests(driver: Driver) -> None:
    top_names = _run_q1(driver)
    _run_q2(driver, top_names)
    _run_q3(driver)
    print(f"\n{'─' * 64}")
    print("  Smoke tests complete.")
    print(f"{'─' * 64}\n")
