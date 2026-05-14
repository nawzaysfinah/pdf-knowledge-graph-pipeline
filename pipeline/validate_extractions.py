"""Post-processing validation and cleaning for Stage 5 extractions.

Reads output/extractions.jsonl, applies strict entity name and ontology
constraints, and writes output/validated_extractions.jsonl.

Usage:
    python -m pipeline.validate_extractions            # clean + write output
    python -m pipeline.validate_extractions --dry-run  # report only, no write
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EXTRACTIONS_PATH          = Path("output") / "extractions.jsonl"
VALIDATED_EXTRACTIONS_PATH = Path("output") / "validated_extractions.jsonl"
ONTOLOGY_PATH             = Path("output") / "ontology.json"

_BOILERPLATE = {
    "External assurance was not sought",
    "This report",
    "The following",
    "As at",
    "Not applicable",
    "See above",
    "Refer to",
}


# ---------------------------------------------------------------------------
# Load valid sets from ontology
# ---------------------------------------------------------------------------

def _load_valid_sets(ontology_path: Path) -> tuple[set[str], set[str]]:
    """Return (VALID_ENTITY_TYPES, VALID_PREDICATES) from ontology.json."""
    data = json.loads(ontology_path.read_text(encoding="utf-8"))
    entity_types = {e["type"] for e in data["entity_types"]}
    predicates   = {r["predicate"].upper() for r in data["relationship_types"]}
    return entity_types, predicates


# ---------------------------------------------------------------------------
# Entity name validation
# ---------------------------------------------------------------------------

def _valid_name(name: Any) -> tuple[bool, str]:
    """Return (is_valid, reason). reason is empty string when valid."""
    if not isinstance(name, str):
        return False, "not_a_string"
    if len(name) < 4:
        return False, "too_short"
    if len(name) > 60:
        return False, "too_long"
    if name[0].islower():
        return False, "starts_lowercase"
    if len(name.split()) >= 9:
        return False, "too_many_words"
    if name.endswith("."):
        return False, "ends_with_period"
    if "\n" in name:
        return False, "contains_newline"
    for phrase in _BOILERPLATE:
        if name.startswith(phrase):
            return False, f"boilerplate:{phrase[:30]}"
    return True, ""


# ---------------------------------------------------------------------------
# Triple validation
# ---------------------------------------------------------------------------

def _valid_triple(
    triple: dict[str, Any],
    valid_entity_types: set[str],
    valid_predicates: set[str],
) -> tuple[bool, str]:
    """Return (is_valid, reason)."""
    predicate = str(triple.get("predicate", "")).upper()
    if predicate not in valid_predicates:
        return False, f"invalid_predicate:{triple.get('predicate','')}"

    confidence = float(triple.get("confidence", 0.0))
    if confidence < 0.6:
        return False, "low_confidence"

    ok, reason = _valid_name(triple.get("subject"))
    if not ok:
        return False, f"bad_subject:{reason}"

    ok, reason = _valid_name(triple.get("object"))
    if not ok:
        return False, f"bad_object:{reason}"

    subj_type = triple.get("subject_type", "")
    if subj_type and subj_type not in valid_entity_types:
        return False, f"invalid_subject_type:{subj_type}"

    obj_type = triple.get("object_type", "")
    if obj_type and obj_type not in valid_entity_types:
        return False, f"invalid_object_type:{obj_type}"

    return True, ""


# ---------------------------------------------------------------------------
# Main cleaning function
# ---------------------------------------------------------------------------

def validate_and_clean(
    extractions_path: Path = EXTRACTIONS_PATH,
    output_path: Path = VALIDATED_EXTRACTIONS_PATH,
    ontology_path: Path = ONTOLOGY_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read extractions.jsonl, filter noise, write validated_extractions.jsonl.

    Returns a stats dict.
    """
    valid_entity_types, valid_predicates = _load_valid_sets(ontology_path)

    stats: dict[str, Any] = {
        "chunks_processed":  0,
        "total_entities":    0,
        "kept_entities":     0,
        "total_triples":     0,
        "kept_triples":      0,
        "zero_triple_chunks": [],
    }
    skip_reasons: Counter = Counter()
    kept_predicates: Counter = Counter()
    kept_entity_types: Counter = Counter()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_handle = None if dry_run else output_path.open("w", encoding="utf-8")

    try:
        with extractions_path.open(encoding="utf-8") as inp:
            for line in inp:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                stats["chunks_processed"] += 1

                # --- Filter entities ---
                clean_entities: list[dict] = []
                for ent in record.get("entities", []):
                    stats["total_entities"] += 1
                    ent_type = ent.get("type", "")
                    ok_name, reason_name = _valid_name(ent.get("name"))
                    if not ok_name:
                        skip_reasons[f"entity_name:{reason_name}"] += 1
                        continue
                    if ent_type not in valid_entity_types:
                        skip_reasons[f"entity_type:{ent_type}"] += 1
                        continue
                    clean_entities.append(ent)
                    stats["kept_entities"] += 1
                    kept_entity_types[ent_type] += 1

                # --- Filter triples ---
                clean_triples: list[dict] = []
                for triple in record.get("triples", []):
                    stats["total_triples"] += 1
                    ok, reason = _valid_triple(triple, valid_entity_types, valid_predicates)
                    if not ok:
                        skip_reasons[reason] += 1
                        continue
                    clean_triples.append(triple)
                    stats["kept_triples"] += 1
                    kept_predicates[triple.get("predicate", "").upper()] += 1

                if not clean_triples and record.get("triples"):
                    stats["zero_triple_chunks"].append(record.get("chunk_id", "unknown"))

                if out_handle is not None:
                    cleaned = {**record, "entities": clean_entities, "triples": clean_triples}
                    out_handle.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
    finally:
        if out_handle is not None:
            out_handle.close()

    stats["skip_reasons"]       = skip_reasons
    stats["kept_predicates"]    = kept_predicates
    stats["kept_entity_types"]  = kept_entity_types
    return stats


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _print_report(stats: dict[str, Any], dry_run: bool) -> None:
    total_e = stats["total_entities"]
    kept_e  = stats["kept_entities"]
    total_t = stats["total_triples"]
    kept_t  = stats["kept_triples"]

    print("\n" + "=" * 60)
    print("  Extraction Validation Report" + ("  [DRY RUN]" if dry_run else ""))
    print("=" * 60)
    print(f"  Chunks processed    : {stats['chunks_processed']}")
    print(f"  Entity retention    : {kept_e}/{total_e}"
          f"  ({kept_e/max(total_e,1)*100:.1f}%)")
    print(f"  Triple retention    : {kept_t}/{total_t}"
          f"  ({kept_t/max(total_t,1)*100:.1f}%)")

    print("\n  Top 10 skip reasons:")
    for reason, count in stats["skip_reasons"].most_common(10):
        print(f"    {count:>6}  {reason}")

    print("\n  Top 10 valid predicates in output:")
    for pred, count in stats["kept_predicates"].most_common(10):
        print(f"    {count:>6}  {pred}")

    print("\n  Top 10 valid entity types in output:")
    for etype, count in stats["kept_entity_types"].most_common(10):
        print(f"    {count:>6}  {etype}")

    zero = stats["zero_triple_chunks"]
    if zero:
        print(f"\n  Chunks with 0 surviving triples ({len(zero)}) — flag for review:")
        for cid in zero[:20]:
            print(f"    {cid}")
        if len(zero) > 20:
            print(f"    ... and {len(zero) - 20} more")

    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and clean extractions.jsonl")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print validation report without writing output file",
    )
    parser.add_argument(
        "--extractions", default=str(EXTRACTIONS_PATH),
        help=f"Input extractions JSONL (default: {EXTRACTIONS_PATH})",
    )
    parser.add_argument(
        "--output", default=str(VALIDATED_EXTRACTIONS_PATH),
        help=f"Output JSONL (default: {VALIDATED_EXTRACTIONS_PATH})",
    )
    args = parser.parse_args()

    extractions_path = Path(args.extractions)
    output_path      = Path(args.output)

    for path, label in [
        (extractions_path, "extractions.jsonl"),
        (ONTOLOGY_PATH,    "ontology.json"),
    ]:
        if not path.exists():
            print(f"ERROR: {path} not found. Run prior stages first.")
            sys.exit(1)

    stats = validate_and_clean(
        extractions_path=extractions_path,
        output_path=output_path,
        dry_run=args.dry_run,
    )
    _print_report(stats, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\n  Output written → {output_path.resolve()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    main()
