"""SQLite-backed pending triple review store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import sqlite3


class ReviewStore:
    """Manage pending extraction payloads and review audit trail."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_triples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    extraction_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pending_id INTEGER NOT NULL,
                    entity_type TEXT NOT NULL,
                    name TEXT,
                    description TEXT,
                    text TEXT,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(pending_id) REFERENCES pending_triples(id)
                );

                CREATE TABLE IF NOT EXISTS relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pending_id INTEGER NOT NULL,
                    source_type TEXT,
                    source_id TEXT,
                    rel TEXT,
                    target_type TEXT,
                    target_key TEXT,
                    target_value TEXT,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(pending_id) REFERENCES pending_triples(id)
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pending_id INTEGER NOT NULL,
                    reviewer TEXT NOT NULL,
                    action TEXT NOT NULL,
                    notes TEXT,
                    edited_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(pending_id) REFERENCES pending_triples(id)
                );

                CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_triples(status);
                CREATE INDEX IF NOT EXISTS idx_pending_doc_id ON pending_triples(doc_id);
                CREATE INDEX IF NOT EXISTS idx_entities_pending ON entities(pending_id);
                CREATE INDEX IF NOT EXISTS idx_relations_pending ON relations(pending_id);
                """
            )

    def enqueue_extraction(self, payload: dict[str, Any]) -> int:
        """Insert a pending extraction payload and decomposed rows."""
        now = datetime.utcnow().isoformat() + "Z"
        doc_id = str(payload.get("doc_id", "")).strip()
        if not doc_id:
            raise ValueError("payload.doc_id is required")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_triples (doc_id, extraction_json, status, created_at, updated_at)
                VALUES (?, ?, 'PENDING', ?, ?)
                """,
                (doc_id, json.dumps(payload), now, now),
            )
            pending_id = int(cursor.lastrowid)
            self._upsert_entities(conn, pending_id, payload)
            self._upsert_relations(conn, pending_id, payload)
            conn.commit()

        return pending_id

    def _upsert_entities(
        self,
        conn: sqlite3.Connection,
        pending_id: int,
        payload: dict[str, Any],
    ) -> None:
        conn.execute("DELETE FROM entities WHERE pending_id = ?", (pending_id,))
        entities = payload.get("entities", {}) or {}
        for entity_type, items in entities.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO entities (pending_id, entity_type, name, description, text, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pending_id,
                        entity_type,
                        str(item.get("name", "")).strip() or None,
                        str(item.get("description", "")).strip() or None,
                        str(item.get("text", "")).strip() or None,
                        json.dumps(item),
                    ),
                )

    def _upsert_relations(
        self,
        conn: sqlite3.Connection,
        pending_id: int,
        payload: dict[str, Any],
    ) -> None:
        conn.execute("DELETE FROM relations WHERE pending_id = ?", (pending_id,))
        relations = payload.get("relations", []) or []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            conn.execute(
                """
                INSERT INTO relations (
                    pending_id, source_type, source_id, rel,
                    target_type, target_key, target_value, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pending_id,
                    str(relation.get("source_type", "")).strip() or None,
                    str(relation.get("source_id", "")).strip() or None,
                    str(relation.get("rel", "")).strip() or None,
                    str(relation.get("target_type", "")).strip() or None,
                    str(relation.get("target_key", "")).strip() or None,
                    str(relation.get("target_value", "")).strip() or None,
                    json.dumps(relation),
                ),
            )

    def get_pending(self, pending_id: int) -> dict[str, Any] | None:
        """Fetch one pending item with entities and relations."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_triples WHERE id = ?",
                (pending_id,),
            ).fetchone()
            if row is None:
                return None

            payload = json.loads(row["extraction_json"])
            payload["_meta"] = {
                "pending_id": row["id"],
                "doc_id": row["doc_id"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            return payload

    def list_pending(self, status: str = "PENDING") -> list[dict[str, Any]]:
        """List payloads by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_triples WHERE status = ? ORDER BY created_at ASC",
                (status,),
            ).fetchall()

        output = []
        for row in rows:
            payload = json.loads(row["extraction_json"])
            payload["_meta"] = {
                "pending_id": row["id"],
                "doc_id": row["doc_id"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            output.append(payload)
        return output

    def list_pending_grouped_by_doc(self) -> dict[str, list[dict[str, Any]]]:
        """Return pending payloads grouped by doc_id for UI display."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for payload in self.list_pending(status="PENDING"):
            grouped.setdefault(payload.get("doc_id", "unknown"), []).append(payload)
        return grouped

    def update_pending_payload(self, pending_id: int, edited_payload: dict[str, Any]) -> None:
        """Update extraction payload after reviewer edits."""
        now = datetime.utcnow().isoformat() + "Z"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pending_triples
                SET extraction_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(edited_payload), now, pending_id),
            )
            self._upsert_entities(conn, pending_id, edited_payload)
            self._upsert_relations(conn, pending_id, edited_payload)
            conn.commit()

    def record_review(
        self,
        pending_id: int,
        reviewer: str,
        action: str,
        notes: str = "",
        edited_payload: dict[str, Any] | None = None,
    ) -> None:
        """Record reviewer decision and set pending status."""
        now = datetime.utcnow().isoformat() + "Z"
        status = "APPROVED" if action.upper() == "APPROVE" else "REJECTED"

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reviews (pending_id, reviewer, action, notes, edited_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    pending_id,
                    reviewer.strip() or "unknown",
                    action.upper(),
                    notes,
                    json.dumps(edited_payload) if edited_payload is not None else None,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE pending_triples
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, pending_id),
            )
            conn.commit()

    def list_reviews(self, pending_id: int) -> list[dict[str, Any]]:
        """List review actions for one pending item."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reviews WHERE pending_id = ? ORDER BY created_at ASC",
                (pending_id,),
            ).fetchall()
        return [dict(row) for row in rows]
