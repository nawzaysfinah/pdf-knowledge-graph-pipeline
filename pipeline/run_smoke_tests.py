"""CLI runner for Stage 9: Smoke Test Queries.

Usage:
    python -m pipeline.run_smoke_tests
"""
from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase

from pipeline.smoke_tests import run_smoke_tests

load_dotenv()
logging.basicConfig(
    level=logging.WARNING,   # suppress driver noise during smoke tests
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    uri      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
    user     = os.environ.get("NEO4J_USER",     "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")

    print(f"\n  Connecting to {uri} ...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        print("  Connected.\n")
        run_smoke_tests(driver)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        sys.exit(1)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
