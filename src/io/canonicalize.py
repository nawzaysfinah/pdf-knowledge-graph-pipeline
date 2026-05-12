"""Canonicalization pipeline entrypoint."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json

from src.config import AppConfig
from src.io.mapping import map_to_canonical


OUTPUT_FILES = {
    "documents": "canonical_documents.csv",
    "divisions": "canonical_divisions.csv",
    "initiatives": "canonical_initiatives.csv",
    "doc_initiatives": "canonical_doc_initiatives.csv",
}


def run_canonicalization(config: AppConfig) -> dict[str, Any]:
    """Generate canonical CSV files from mapped raw or sample data."""
    canonical_dir: Path = config.paths.data_canonical
    canonical_dir.mkdir(parents=True, exist_ok=True)

    mapped_tables, metadata = map_to_canonical(
        data_raw=config.paths.data_raw,
        data_sample=config.paths.data_sample,
        mapping_config_path=config.paths.mapping_config,
        fallback_config_path=config.paths.mapping_config_sample,
    )

    output_paths: dict[str, str] = {}
    for key, df in mapped_tables.items():
        path = canonical_dir / OUTPUT_FILES[key]
        df.to_csv(path, index=False)
        output_paths[key] = str(path)

    run_summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "metadata": metadata,
        "output_paths": output_paths,
        "row_counts": {key: int(len(df)) for key, df in mapped_tables.items()},
    }

    with (canonical_dir / "canonicalization_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(run_summary, handle, indent=2)

    return run_summary
