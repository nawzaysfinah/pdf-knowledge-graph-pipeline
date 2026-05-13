"""Stage 7: Validation and Filtering.

Processing pipeline per triple:
  1. Apply canonical_map  — resolve surface forms to canonical names + IDs
  2. Confidence filter    — drop triples with confidence < CONFIDENCE_THRESHOLD
  3. Ontology validation  — flag (but keep) triples that violate type constraints

Outputs:
  output/validated_triples.jsonl  — all triples that passed confidence filter
  output/validation_report.txt    — human-readable audit report
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from pipeline.ontology import Ontology, load_ontology
from pipeline.entity_resolver import load_canonical_map

logger = logging.getLogger(__name__)

EXTRACTIONS_PATH       = Path("output") / "extractions.jsonl"
CANONICAL_MAP_PATH     = Path("output") / "canonical_map.json"
VALIDATED_PATH         = Path("output") / "validated_triples.jsonl"
REPORT_PATH            = Path("output") / "validation_report.txt"
ONTOLOGY_PATH          = Path("output") / "ontology.json"

CONFIDENCE_THRESHOLD   = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _triple_id(triple: dict[str, Any]) -> str:
    key = f"{triple.get('chunk_id','')}:{triple.get('subject','')}:{triple.get('predicate','')}:{triple.get('object','')}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _resolve(name: str, canonical_map: dict[str, Any]) -> tuple[str, str | None]:
    """Return (canonical_name, canonical_id) for a surface form.
    Falls back to the original name and None if not in the map.
    """
    entry = canonical_map.get(name)
    if entry:
        return entry["canonical_name"], entry["canonical_id"]
    return name, None


def _entity_type(name: str, canonical_map: dict[str, Any]) -> str | None:
    entry = canonical_map.get(name)
    return entry["type"] if entry else None


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_triple(
    raw: dict[str, Any],
    canonical_map: dict[str, Any],
    ontology: Ontology,
) -> dict[str, Any] | None:
    """Apply canonicalisation, confidence filter, and ontology validation.

    Returns the enriched triple dict, or None if it fails the confidence filter.
    """
    confidence = float(raw.get("confidence", 0.0))
    if confidence < CONFIDENCE_THRESHOLD:
        return None

    subj_surface = str(raw.get("subject", "")).strip()
    obj_surface  = str(raw.get("object",  "")).strip()
    predicate    = str(raw.get("predicate", "")).strip()

    subj_canonical, subj_cid = _resolve(subj_surface, canonical_map)
    obj_canonical,  obj_cid  = _resolve(obj_surface,  canonical_map)

    # Use canonical_map types where available; fall back to LLM-reported types
    subj_type = (
        canonical_map[subj_surface]["type"]
        if subj_surface in canonical_map
        else str(raw.get("subject_type", ""))
    )
    obj_type = (
        canonical_map[obj_surface]["type"]
        if obj_surface in canonical_map
        else str(raw.get("object_type", ""))
    )

    # Ontology constraint check
    ontology_valid = ontology.is_valid_triple(subj_type, predicate, obj_type)
    violation: str | None = None
    if not ontology_valid:
        if predicate not in ontology.predicate_constraints:
            violation = f"Unknown predicate '{predicate}'"
        else:
            constraint = ontology.predicate_constraints[predicate]
            parts = []
            if subj_type not in constraint["subject"]:
                parts.append(f"subject type '{subj_type}' not allowed for '{predicate}'")
            if obj_type not in constraint["object"]:
                parts.append(f"object type '{obj_type}' not allowed for '{predicate}'")
            violation = "; ".join(parts) if parts else f"constraint violation for '{predicate}'"

    return {
        "triple_id":          _triple_id(raw),
        "subject":            subj_canonical,
        "subject_surface":    subj_surface,
        "subject_canonical_id": subj_cid,
        "subject_type":       subj_type,
        "predicate":          predicate,
        "object":             obj_canonical,
        "object_surface":     obj_surface,
        "object_canonical_id": obj_cid,
        "object_type":        obj_type,
        "evidence":           raw.get("evidence", ""),
        "confidence":         confidence,
        "chunk_id":           raw.get("chunk_id", ""),
        "doc_id":             raw.get("doc_id", ""),
        "filename":           raw.get("filename", ""),
        "page_num":           raw.get("page_num", 0),
        "section_heading":    raw.get("section_heading", ""),
        "ontology_valid":     ontology_valid,
        "violation":          violation,
    }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_validation(
    extractions_path: Path = EXTRACTIONS_PATH,
    canonical_map_path: Path = CANONICAL_MAP_PATH,
    ontology_path: Path = ONTOLOGY_PATH,
    validated_path: Path = VALIDATED_PATH,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    """Validate all triples from extractions.jsonl.

    Returns a stats dict and writes both output files.
    """
    ontology      = load_ontology(ontology_path)
    canonical_map = load_canonical_map(canonical_map_path)

    stats: dict[str, Any] = {
        "total_raw":          0,
        "filtered_low_conf":  0,
        "ontology_valid":     0,
        "ontology_violations": 0,
        "written":            0,
    }
    violations: list[dict[str, Any]] = []

    validated_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        extractions_path.open() as inp,
        validated_path.open("w", encoding="utf-8") as out,
    ):
        for line in inp:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)

            for raw_triple in record.get("triples", []):
                stats["total_raw"] += 1
                result = validate_triple(raw_triple, canonical_map, ontology)

                if result is None:
                    stats["filtered_low_conf"] += 1
                    continue

                if result["ontology_valid"]:
                    stats["ontology_valid"] += 1
                else:
                    stats["ontology_violations"] += 1
                    violations.append(result)

                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                stats["written"] += 1

    _write_report(stats, violations, report_path)
    return stats


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _write_report(
    stats: dict[str, Any],
    violations: list[dict[str, Any]],
    report_path: Path,
) -> None:
    lines: list[str] = [
        "Knowledge Graph — Validation Report",
        "=" * 60,
        "",
        f"  Total triples from LLM      : {stats['total_raw']}",
        f"  Filtered (confidence < 0.7) : {stats['filtered_low_conf']}",
        f"  Written to validated file   : {stats['written']}",
        f"    of which ontology-valid   : {stats['ontology_valid']}",
        f"    of which violations       : {stats['ontology_violations']}",
        "",
    ]

    if violations:
        lines += [
            f"ONTOLOGY VIOLATIONS  ({len(violations)} triple(s) — kept for review)",
            "-" * 60,
        ]
        # Group by violation type
        by_violation: dict[str, list[dict]] = defaultdict(list)
        for v in violations:
            by_violation[v["violation"] or "unknown"].append(v)

        for viol_msg, triples in by_violation.items():
            lines.append(f"\n  [{viol_msg}]  ({len(triples)} triple(s))")
            for t in triples:
                lines.append(
                    f"    ({t['subject_type']}) {t['subject']!r}"
                    f" --{t['predicate']}--> "
                    f"({t['object_type']}) {t['object']!r}"
                )
                lines.append(f"    evidence : {t['evidence']!r}")
                lines.append(f"    source   : {t['filename']}  p.{t['page_num']}")
                lines.append("")
    else:
        lines += ["No ontology violations found.", ""]

    lines += ["=" * 60]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Validation report → %s", report_path)
