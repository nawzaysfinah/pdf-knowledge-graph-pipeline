from __future__ import annotations

from pathlib import Path

from src.io.mapping import map_to_canonical


def test_map_to_canonical_with_unknown_schema(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    sample_dir = tmp_path / "sample"
    raw_dir.mkdir()
    sample_dir.mkdir()

    (raw_dir / "docs.csv").write_text(
        "id_col,title_col,body_col,team_col,date_col,type_col,uri_col\n"
        "D-A,Doc A,Some text A,Team One,2024-01-01,memo,local://a\n"
        ",Doc B,Some text B,Team Two,2024-01-02,report,local://b\n"
        "D-C,Doc C,,Team Two,2024-01-03,memo,local://c\n",
        encoding="utf-8",
    )

    mapping_file = tmp_path / "mapping.yaml"
    mapping_file.write_text(
        """
        documents:
          file: "docs.csv"
          columns:
            doc_id: "id_col"
            title: "title_col"
            text: "body_col"
            division: "team_col"
            date: "date_col"
            doc_type: "type_col"
            source_uri: "uri_col"
        """,
        encoding="utf-8",
    )

    tables, metadata = map_to_canonical(
        data_raw=raw_dir,
        data_sample=sample_dir,
        mapping_config_path=mapping_file,
        fallback_config_path=mapping_file,
    )

    docs = tables["documents"]
    divisions = tables["divisions"]

    assert len(docs) == 2  # row with empty text is dropped
    assert set(docs.columns.tolist()) == {
        "doc_id",
        "title",
        "text",
        "division",
        "date",
        "doc_type",
        "source_uri",
    }
    assert docs["doc_id"].str.strip().ne("").all()  # missing doc_id gets generated
    assert len(divisions) == 2  # derived from documents.division
    assert metadata["documents_rows"] == 2


def test_map_to_canonical_fallback_to_sample(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    sample_dir = tmp_path / "sample"
    raw_dir.mkdir()
    sample_dir.mkdir()

    (sample_dir / "docs.csv").write_text(
        "doc_ref,headline,body_text\nD1,T1,Body\n",
        encoding="utf-8",
    )

    fallback = tmp_path / "mapping.sample.yaml"
    fallback.write_text(
        """
        documents:
          file: "docs.csv"
          columns:
            doc_id: "doc_ref"
            title: "headline"
            text: "body_text"
        """,
        encoding="utf-8",
    )

    missing_primary = tmp_path / "mapping.yaml"

    tables, _ = map_to_canonical(
        data_raw=raw_dir,
        data_sample=sample_dir,
        mapping_config_path=missing_primary,
        fallback_config_path=fallback,
    )

    assert len(tables["documents"]) == 1
    assert tables["documents"].iloc[0]["doc_id"] == "D1"
