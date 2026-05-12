"""CLI runner for Stage 8: Neo4j Ingestion.

Usage:
    python -m pipeline.run_ingest
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.neo4j_ingester import (
    CANONICAL_MAP_PATH,
    VALIDATED_PATH,
    ingest,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    neo4j_uri      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
    neo4j_user     = os.environ.get("NEO4J_USER",     "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "changeme")

    for path, label in [
        (VALIDATED_PATH,     "validated_triples.jsonl"),
        (CANONICAL_MAP_PATH, "canonical_map.json"),
    ]:
        if not path.exists():
            print(f"ERROR: {path} not found. Run prior stages first.")
            sys.exit(1)

    print(f"\n  Neo4j URI  : {neo4j_uri}")
    print(f"  User       : {neo4j_user}")
    print(f"  Triples    : {VALIDATED_PATH}")
    print(f"  Canon map  : {CANONICAL_MAP_PATH}\n")

    ingest(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
    )

    print(f"\n  Graph browser: http://localhost:7474")


if __name__ == "__main__":
    main()
