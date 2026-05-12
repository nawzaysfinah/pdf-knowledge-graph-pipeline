"""Map unknown raw CSV schemas into canonical internal tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import pandas as pd
import yaml

from src.utils.ids import make_stable_id
from src.utils.text import normalize_whitespace, slugify


CANONICAL_COLUMNS: dict[str, list[str]] = {
    "documents": [
        "doc_id",
        "title",
        "text",
        "division",
        "date",
        "doc_type",
        "source_uri",
    ],
    "divisions": ["division_id", "name"],
    "initiatives": ["initiative_id", "name", "description"],
    "doc_initiatives": ["doc_id", "initiative_id"],
}

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "documents": ["doc_id", "text"],
    "divisions": ["division_id", "name"],
    "initiatives": ["initiative_id", "name"],
    "doc_initiatives": ["doc_id", "initiative_id"],
}


@dataclass
class MappingTableConfig:
    file: str
    columns: dict[str, str]


@dataclass
class MappingConfig:
    documents: MappingTableConfig
    divisions: MappingTableConfig | None = None
    initiatives: MappingTableConfig | None = None
    doc_initiatives: MappingTableConfig | None = None


class MappingError(RuntimeError):
    """Raised when mapping configuration is invalid."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise MappingError(f"Mapping config is not a dict: {path}")
    return data


def load_mapping_config(
    mapping_config_path: Path,
    fallback_config_path: Path,
) -> tuple[MappingConfig, Path]:
    """Load mapping config, falling back to sample config when needed."""
    selected_path = mapping_config_path if mapping_config_path.exists() else fallback_config_path
    raw = _load_yaml(selected_path)

    if "documents" not in raw:
        if selected_path != fallback_config_path and fallback_config_path.exists():
            raw = _load_yaml(fallback_config_path)
            selected_path = fallback_config_path
        else:
            raise MappingError("Mapping config must contain a 'documents' section.")

    def parse_table(name: str, required: bool = False) -> MappingTableConfig | None:
        section = raw.get(name)
        if section is None:
            if required:
                raise MappingError(f"Missing required table config: {name}")
            return None
        if not isinstance(section, dict) or "file" not in section or "columns" not in section:
            raise MappingError(
                f"Table '{name}' must include 'file' and 'columns'. Received: {json.dumps(section)}"
            )
        return MappingTableConfig(file=str(section["file"]), columns=dict(section["columns"]))

    cfg = MappingConfig(
        documents=parse_table("documents", required=True),
        divisions=parse_table("divisions"),
        initiatives=parse_table("initiatives"),
        doc_initiatives=parse_table("doc_initiatives"),
    )
    return cfg, selected_path


def _resolve_file(input_file: str, data_raw: Path, data_sample: Path) -> Path:
    candidate = Path(input_file)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    raw_candidate = data_raw / input_file
    if raw_candidate.exists():
        return raw_candidate

    sample_candidate = data_sample / input_file
    if sample_candidate.exists():
        return sample_candidate

    if candidate.exists():
        return candidate

    raise FileNotFoundError(f"Could not resolve mapped CSV file: {input_file}")


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _map_table(
    df: pd.DataFrame,
    column_map: dict[str, str],
    target_columns: list[str],
) -> pd.DataFrame:
    mapped: dict[str, pd.Series] = {}
    for target in target_columns:
        source = column_map.get(target)
        if source and source in df.columns:
            mapped[target] = df[source].astype(str).map(normalize_whitespace)
        else:
            mapped[target] = pd.Series([""] * len(df), dtype=str)

    result = pd.DataFrame(mapped)
    return result[target_columns]


def _ensure_document_ids(documents_df: pd.DataFrame) -> pd.DataFrame:
    missing = documents_df["doc_id"].astype(str).str.strip() == ""
    if missing.any():
        generated = []
        for _, row in documents_df[missing].iterrows():
            seed = row.get("title", "") or row.get("text", "")[:120]
            generated.append(make_stable_id("doc", seed))
        documents_df.loc[missing, "doc_id"] = generated

    documents_df = documents_df.drop_duplicates(subset=["doc_id"], keep="first")
    documents_df = documents_df[documents_df["text"].astype(str).str.strip() != ""]
    return documents_df


def _derive_divisions_from_documents(documents_df: pd.DataFrame) -> pd.DataFrame:
    divisions = (
        documents_df[documents_df["division"].astype(str).str.strip() != ""]["division"]
        .drop_duplicates()
        .to_frame()
    )
    if divisions.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS["divisions"])

    divisions["name"] = divisions["division"]
    divisions["division_id"] = divisions["name"].map(lambda x: f"division_{slugify(x)}")
    return divisions[["division_id", "name"]]


def map_to_canonical(
    data_raw: Path,
    data_sample: Path,
    mapping_config_path: Path,
    fallback_config_path: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Map configured raw tables into canonical DataFrames."""
    cfg, selected_config = load_mapping_config(mapping_config_path, fallback_config_path)

    docs_file = _resolve_file(cfg.documents.file, data_raw=data_raw, data_sample=data_sample)
    docs_raw = _read_csv(docs_file)
    documents_df = _map_table(docs_raw, cfg.documents.columns, CANONICAL_COLUMNS["documents"])
    documents_df = _ensure_document_ids(documents_df)

    def map_optional(table_cfg: MappingTableConfig | None, table_name: str) -> pd.DataFrame:
        if table_cfg is None:
            return pd.DataFrame(columns=CANONICAL_COLUMNS[table_name])
        file_path = _resolve_file(table_cfg.file, data_raw=data_raw, data_sample=data_sample)
        raw_df = _read_csv(file_path)
        mapped_df = _map_table(raw_df, table_cfg.columns, CANONICAL_COLUMNS[table_name])
        return mapped_df.drop_duplicates().reset_index(drop=True)

    divisions_df = map_optional(cfg.divisions, "divisions")
    if divisions_df.empty:
        divisions_df = _derive_divisions_from_documents(documents_df)

    initiatives_df = map_optional(cfg.initiatives, "initiatives")
    doc_initiatives_df = map_optional(cfg.doc_initiatives, "doc_initiatives")

    metadata = {
        "mapping_config_used": str(selected_config),
        "input_documents_file": str(docs_file),
        "documents_rows": int(len(documents_df)),
        "divisions_rows": int(len(divisions_df)),
        "initiatives_rows": int(len(initiatives_df)),
        "doc_initiatives_rows": int(len(doc_initiatives_df)),
    }

    return {
        "documents": documents_df,
        "divisions": divisions_df,
        "initiatives": initiatives_df,
        "doc_initiatives": doc_initiatives_df,
    }, metadata
