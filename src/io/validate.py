"""Validation utilities for canonical datasets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json

import pandas as pd

from src.io.mapping import CANONICAL_COLUMNS, REQUIRED_COLUMNS


def _null_rates(df: pd.DataFrame) -> dict[str, float]:
    rates: dict[str, float] = {}
    if df.empty:
        for column in df.columns:
            rates[column] = 1.0
        return rates

    for column in df.columns:
        missing = (df[column].astype(str).str.strip() == "").sum()
        rates[column] = round(float(missing) / max(len(df), 1), 4)
    return rates


def _validate_table(path: Path, table_name: str) -> dict[str, Any]:
    required = REQUIRED_COLUMNS[table_name]
    expected = CANONICAL_COLUMNS[table_name]

    if not path.exists():
        return {
            "exists": False,
            "row_count": 0,
            "missing_required_columns": required,
            "missing_expected_columns": expected,
            "null_rates": {},
        }

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    columns = set(df.columns)
    missing_required = [col for col in required if col not in columns]
    missing_expected = [col for col in expected if col not in columns]

    null_rates = _null_rates(df)
    return {
        "exists": True,
        "row_count": int(len(df)),
        "missing_required_columns": missing_required,
        "missing_expected_columns": missing_expected,
        "null_rates": null_rates,
    }


def validate_canonical(canonical_dir: Path) -> dict[str, Any]:
    """Validate canonical files and persist a JSON report."""
    mapping = {
        "documents": canonical_dir / "canonical_documents.csv",
        "divisions": canonical_dir / "canonical_divisions.csv",
        "initiatives": canonical_dir / "canonical_initiatives.csv",
        "doc_initiatives": canonical_dir / "canonical_doc_initiatives.csv",
    }

    tables = {name: _validate_table(path, name) for name, path in mapping.items()}
    issues = []
    for name, result in tables.items():
        if not result["exists"]:
            issues.append(f"{name}: missing file")
        if result["missing_required_columns"]:
            issues.append(
                f"{name}: missing required columns {result['missing_required_columns']}"
            )

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "canonical_dir": str(canonical_dir),
        "tables": tables,
        "issues": issues,
        "status": "ok" if not issues else "warning",
    }

    report_path = canonical_dir / "validation_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    return report
