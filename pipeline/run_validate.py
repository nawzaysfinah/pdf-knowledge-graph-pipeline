"""CLI runner for Stage 7: Validation and Filtering.

Usage:
    python -m pipeline.run_validate
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.validator import (
    EXTRACTIONS_PATH,
    CANONICAL_MAP_PATH,
    ONTOLOGY_PATH,
    VALIDATED_PATH,
    REPORT_PATH,
    CONFIDENCE_THRESHOLD,
    run_validation,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    for path, label in [
        (EXTRACTIONS_PATH,   "extractions.jsonl"),
        (CANONICAL_MAP_PATH, "canonical_map.json"),
        (ONTOLOGY_PATH,      "ontology.json"),
    ]:
        if not path.exists():
            print(f"ERROR: {path} not found. Run prior stages first.")
            sys.exit(1)

    print(f"\n  Confidence threshold : {CONFIDENCE_THRESHOLD}")
    print(f"  Input                : {EXTRACTIONS_PATH}")
    print(f"  Canonical map        : {CANONICAL_MAP_PATH}")
    print(f"  Output triples       : {VALIDATED_PATH}")
    print(f"  Report               : {REPORT_PATH}\n")

    stats = run_validation()

    print("── Validation Summary ───────────────────────────────────")
    print(f"  Total raw triples           : {stats['total_raw']}")
    print(f"  Filtered (confidence < {CONFIDENCE_THRESHOLD}) : {stats['filtered_low_conf']}")
    print(f"  Written to validated file   : {stats['written']}")
    print(f"    ✓ Ontology-valid          : {stats['ontology_valid']}")
    print(f"    ✗ Violations (kept)       : {stats['ontology_violations']}")
    print(f"\n  Full report → {REPORT_PATH.resolve()}")

    if stats["ontology_violations"]:
        print(f"\n── Violation Detail (from {REPORT_PATH.name}) ───────────────")
        print(REPORT_PATH.read_text())


if __name__ == "__main__":
    main()
