"""Load canonical data and reviewed triples into Neo4j."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.graph.neo4j_client import Neo4jClient
from src.utils.ids import make_stable_id
from src.utils.text import slugify


class GraphLoader:
    """Handles schema setup and graph loading operations."""

    def __init__(self, client: Neo4jClient) -> None:
        self.client = client

    def ensure_schema(self, constraints_path: Path, indexes_path: Path) -> None:
        self.client.execute_script(constraints_path)
        self.client.execute_script(indexes_path)

    def _read_csv(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, dtype=str, keep_default_na=False)

    def load_canonical(self, canonical_dir: Path) -> dict[str, int]:
        docs_df = self._read_csv(canonical_dir / "canonical_documents.csv")
        divisions_df = self._read_csv(canonical_dir / "canonical_divisions.csv")
        initiatives_df = self._read_csv(canonical_dir / "canonical_initiatives.csv")
        doc_inits_df = self._read_csv(canonical_dir / "canonical_doc_initiatives.csv")

        if not docs_df.empty:
            docs_df = docs_df.fillna("")
            docs_df["division_id"] = docs_df["division"].map(
                lambda x: f"division_{slugify(x)}" if str(x).strip() else ""
            )
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (d:Document {doc_id: row.doc_id})
                SET d.title = row.title,
                    d.text = row.text,
                    d.date = row.date,
                    d.doc_type = row.doc_type,
                    d.source_uri = row.source_uri
                FOREACH (_ IN CASE WHEN row.division_id <> '' THEN [1] ELSE [] END |
                    MERGE (div:Division {division_id: row.division_id})
                    SET div.name = row.division
                    MERGE (d)-[:CREATED_BY]->(div)
                )
                """,
                params={"rows": docs_df.to_dict("records")},
                write=True,
            )

        if not divisions_df.empty:
            divisions_df = divisions_df.fillna("")
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (d:Division {division_id: row.division_id})
                SET d.name = row.name
                """,
                params={"rows": divisions_df.to_dict("records")},
                write=True,
            )

        if not initiatives_df.empty:
            initiatives_df = initiatives_df.fillna("")
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (i:Initiative {initiative_id: row.initiative_id})
                SET i.name = row.name,
                    i.description = row.description
                """,
                params={"rows": initiatives_df.to_dict("records")},
                write=True,
            )

        if not doc_inits_df.empty:
            doc_inits_df = doc_inits_df.fillna("")
            self.client.run_query(
                """
                UNWIND $rows AS row
                MATCH (d:Document {doc_id: row.doc_id})
                MERGE (i:Initiative {initiative_id: row.initiative_id})
                MERGE (d)-[:ABOUT]->(i)
                """,
                params={"rows": doc_inits_df.to_dict("records")},
                write=True,
            )

        self._derive_initiative_ownership()

        return {
            "documents": int(len(docs_df)),
            "divisions": int(len(divisions_df)),
            "initiatives": int(len(initiatives_df)),
            "doc_initiatives": int(len(doc_inits_df)),
        }

    def _derive_initiative_ownership(self) -> None:
        self.client.run_query("MATCH (:Initiative)-[r:OWNED_BY]->(:Division) DELETE r", write=True)
        self.client.run_query(
            """
            MATCH (i:Initiative)<-[:ABOUT]-(d:Document)-[:CREATED_BY]->(div:Division)
            WITH i, div, count(*) AS c
            ORDER BY i.initiative_id, c DESC
            WITH i, collect(div)[0] AS owner
            FOREACH (_ IN CASE WHEN owner IS NULL THEN [] ELSE [1] END |
                MERGE (i)-[:OWNED_BY]->(owner)
            )
            """,
            write=True,
        )

    def apply_postcompute(self, postcompute_script: Path) -> None:
        self.client.execute_script(postcompute_script)

    def upsert_extraction_payload(self, payload: dict[str, Any]) -> None:
        doc_id = str(payload.get("doc_id", "")).strip()
        if not doc_id:
            return

        entities = payload.get("entities", {}) or {}
        relations = payload.get("relations", []) or []

        self.client.run_query(
            "MERGE (d:Document {doc_id: $doc_id})",
            params={"doc_id": doc_id},
            write=True,
        )

        initiatives = []
        for item in entities.get("initiatives", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            initiatives.append(
                {
                    "initiative_id": make_stable_id("initiative", name),
                    "name": name,
                    "description": str(item.get("description", "")).strip(),
                }
            )
        if initiatives:
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (i:Initiative {initiative_id: row.initiative_id})
                SET i.name = row.name,
                    i.description = CASE WHEN row.description <> '' THEN row.description ELSE i.description END
                """,
                params={"rows": initiatives},
                write=True,
            )

        topics = []
        for item in entities.get("topics", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            topics.append({"topic_id": make_stable_id("topic", name), "name": name})
        if topics:
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (t:Topic {topic_id: row.topic_id})
                SET t.name = row.name
                """,
                params={"rows": topics},
                write=True,
            )

        issues = []
        for item in entities.get("issues", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            issues.append({"issue_id": make_stable_id("issue", name), "name": name})
        if issues:
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (i:Issue {issue_id: row.issue_id})
                SET i.name = row.name
                """,
                params={"rows": issues},
                write=True,
            )

        learnings = []
        for item in entities.get("learnings", []):
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            learnings.append({"learning_id": make_stable_id("learning", text), "text": text})
        if learnings:
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (l:Learning {learning_id: row.learning_id})
                SET l.text = row.text
                """,
                params={"rows": learnings},
                write=True,
            )

        outcomes = []
        for item in entities.get("outcomes", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            outcomes.append({"outcome_id": make_stable_id("outcome", name), "name": name})
        if outcomes:
            self.client.run_query(
                """
                UNWIND $rows AS row
                MERGE (o:Outcome {outcome_id: row.outcome_id})
                SET o.name = row.name
                """,
                params={"rows": outcomes},
                write=True,
            )

        self._upsert_relations(doc_id=doc_id, relations=relations)

    def _upsert_relations(self, doc_id: str, relations: list[dict[str, Any]]) -> None:
        for relation in relations:
            rel = str(relation.get("rel", "")).strip()
            source_type = str(relation.get("source_type", "")).strip()
            target_type = str(relation.get("target_type", "")).strip()
            source_id = str(relation.get("source_id", doc_id)).strip() or doc_id
            target_value = str(relation.get("target_value", "")).strip()

            if not rel or not target_value:
                continue

            if source_type == "Document" and target_type == "Initiative" and rel == "ABOUT":
                self.client.run_query(
                    """
                    MATCH (d:Document {doc_id: $doc_id})
                    MATCH (i:Initiative {initiative_id: $initiative_id})
                    MERGE (d)-[:ABOUT]->(i)
                    """,
                    params={
                        "doc_id": source_id,
                        "initiative_id": make_stable_id("initiative", target_value),
                    },
                    write=True,
                )

            if source_type == "Document" and target_type == "Topic" and rel == "MENTIONS":
                self.client.run_query(
                    """
                    MATCH (d:Document {doc_id: $doc_id})
                    MATCH (t:Topic {topic_id: $topic_id})
                    MERGE (d)-[:MENTIONS]->(t)
                    """,
                    params={"doc_id": source_id, "topic_id": make_stable_id("topic", target_value)},
                    write=True,
                )

            if source_type == "Document" and target_type == "Learning" and rel == "CAPTURES":
                self.client.run_query(
                    """
                    MATCH (d:Document {doc_id: $doc_id})
                    MATCH (l:Learning {learning_id: $learning_id})
                    MERGE (d)-[:CAPTURES]->(l)
                    """,
                    params={
                        "doc_id": source_id,
                        "learning_id": make_stable_id("learning", target_value),
                    },
                    write=True,
                )

            if source_type == "Learning" and target_type == "Topic" and rel == "RELATES_TO":
                learning_id = make_stable_id(
                    "learning",
                    str(relation.get("source_value", source_id) or source_id),
                )
                self.client.run_query(
                    """
                    MATCH (l:Learning {learning_id: $learning_id})
                    MATCH (t:Topic {topic_id: $topic_id})
                    MERGE (l)-[:RELATES_TO]->(t)
                    """,
                    params={"learning_id": learning_id, "topic_id": make_stable_id("topic", target_value)},
                    write=True,
                )

            if source_type == "Learning" and target_type == "Issue" and rel == "ADDRESSES":
                learning_id = make_stable_id(
                    "learning",
                    str(relation.get("source_value", source_id) or source_id),
                )
                self.client.run_query(
                    """
                    MATCH (l:Learning {learning_id: $learning_id})
                    MATCH (i:Issue {issue_id: $issue_id})
                    MERGE (l)-[:ADDRESSES]->(i)
                    """,
                    params={"learning_id": learning_id, "issue_id": make_stable_id("issue", target_value)},
                    write=True,
                )

            if source_type == "Initiative" and target_type == "Issue" and rel == "ADDRESSES":
                initiative_id = make_stable_id(
                    "initiative",
                    str(relation.get("source_value", source_id) or source_id),
                )
                self.client.run_query(
                    """
                    MATCH (n:Initiative {initiative_id: $initiative_id})
                    MATCH (i:Issue {issue_id: $issue_id})
                    MERGE (n)-[:ADDRESSES]->(i)
                    """,
                    params={"initiative_id": initiative_id, "issue_id": make_stable_id("issue", target_value)},
                    write=True,
                )

            if source_type == "Initiative" and target_type == "Outcome" and rel == "RESULTED_IN":
                initiative_id = make_stable_id(
                    "initiative",
                    str(relation.get("source_value", source_id) or source_id),
                )
                self.client.run_query(
                    """
                    MATCH (n:Initiative {initiative_id: $initiative_id})
                    MATCH (o:Outcome {outcome_id: $outcome_id})
                    MERGE (n)-[:RESULTED_IN]->(o)
                    """,
                    params={
                        "initiative_id": initiative_id,
                        "outcome_id": make_stable_id("outcome", target_value),
                    },
                    write=True,
                )
