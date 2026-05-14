"""CLI runner for Stage 7: Validation and Filtering.

Two-phase process:
  Phase 7a — validate_extractions.py: enforce ontology + name constraints,
              write output/validated_extractions.jsonl
  Phase 7b — validator.py: confidence filter, canonical resolution,
              ontology type-constraint check, write validated_triples.jsonl

Usage:
    python -m pipeline.run_validate
    python -m pipeline.run_validate --dry-run   # Phase 7a report only
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.validate_extractions import (
    EXTRACTIONS_PATH,
    VALIDATED_EXTRACTIONS_PATH,
    validate_and_clean,
    _print_report,
)
from pipeline.validator import (
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
    parser = argparse.ArgumentParser(description="Stage 7: validate + filter extractions")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run Phase 7a report only — do not write any output files",
    )
    args = parser.parse_args()

    for path, label in [
        (EXTRACTIONS_PATH,   "extractions.jsonl"),
        (CANONICAL_MAP_PATH, "canonical_map.json"),
        (ONTOLOGY_PATH,      "ontology.json"),
    ]:
        if not path.exists():
            print(f"ERROR: {path} not found. Run prior stages first.")
            sys.exit(1)

    # ── Phase 7a: enforce ontology + name constraints ─────────────────────
    print("\n── Phase 7a: Extraction Cleaning ────────────────────────")
    print(f"  Input  : {EXTRACTIONS_PATH}")
    print(f"  Output : {VALIDATED_EXTRACTIONS_PATH}")

    stats_7a = validate_and_clean(
        extractions_path=EXTRACTIONS_PATH,
        output_path=VALIDATED_EXTRACTIONS_PATH,
        dry_run=args.dry_run,
    )
    _print_report(stats_7a, dry_run=args.dry_run)

    if args.dry_run:
        print("\n  [dry-run] Stopping after Phase 7a report.")
        return

    # ── Phase 7b: confidence filter + canonical resolution ────────────────
    print("\n── Phase 7b: Triple Validation ──────────────────────────")
    print(f"  Confidence threshold : {CONFIDENCE_THRESHOLD}")
    print(f"  Input                : {VALIDATED_EXTRACTIONS_PATH}")
    print(f"  Canonical map        : {CANONICAL_MAP_PATH}")
    print(f"  Output triples       : {VALIDATED_PATH}")
    print(f"  Report               : {REPORT_PATH}\n")

    stats_7b = run_validation(
        extractions_path=VALIDATED_EXTRACTIONS_PATH,
        canonical_map_path=CANONICAL_MAP_PATH,
        ontology_path=ONTOLOGY_PATH,
        validated_path=VALIDATED_PATH,
        report_path=REPORT_PATH,
    )

    print("── Phase 7b Summary ─────────────────────────────────────")
    print(f"  Total raw triples           : {stats_7b['total_raw']}")
    print(f"  Filtered (confidence < {CONFIDENCE_THRESHOLD}) : {stats_7b['filtered_low_conf']}")
    print(f"  Written to validated file   : {stats_7b['written']}")
    print(f"    ✓ Ontology-valid          : {stats_7b['ontology_valid']}")
    print(f"    ✗ Violations (kept)       : {stats_7b['ontology_violations']}")
    print(f"\n  Full report → {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    main()
