"""Thin Neo4j driver wrapper for local graph operations."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any


def _import_graph_database():  # type: ignore[no-untyped-def]
    """
    Import Neo4j driver safely even when repository has a top-level `neo4j/` folder.
    """
    repo_root = Path(__file__).resolve().parents[2]

    removed_paths: list[str] = []
    for raw_path in list(sys.path):
        try:
            if Path(raw_path).resolve() == repo_root:
                sys.path.remove(raw_path)
                removed_paths.append(raw_path)
        except Exception:
            continue

    local_module = sys.modules.get("neo4j")
    if local_module is not None:
        module_file = str(getattr(local_module, "__file__", "") or "")
        module_paths = [str(p) for p in getattr(local_module, "__path__", [])]
        if module_file.startswith(str(repo_root)) or any(
            path.startswith(str(repo_root)) for path in module_paths
        ):
            sys.modules.pop("neo4j", None)

    try:
        module = importlib.import_module("neo4j")
        graph_database = getattr(module, "GraphDatabase", None)
        if graph_database is None:
            raise ImportError("Installed neo4j package does not expose GraphDatabase.")
        return graph_database
    finally:
        for raw_path in reversed(removed_paths):
            if raw_path not in sys.path:
                sys.path.insert(0, raw_path)


GraphDatabase = _import_graph_database()


class Neo4jClient:
    """Simple Neo4j query client with script execution support."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self) -> None:
        self._driver.close()

    def ping(self) -> bool:
        with self._driver.session(database=self.database) as session:
            result = session.run("RETURN 1 AS ok")
            return result.single()["ok"] == 1

    def run_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        write: bool = False,
    ) -> list[dict[str, Any]]:
        with self._driver.session(database=self.database) as session:
            executor = session.execute_write if write else session.execute_read
            records = executor(lambda tx: list(tx.run(cypher, params or {})))
        return [record.data() for record in records]

    def execute_script(self, script_path: Path) -> None:
        content = script_path.read_text(encoding="utf-8")
        statements = [stmt.strip() for stmt in content.split(";") if stmt.strip()]
        for statement in statements:
            self.run_query(statement, write=True)

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        self.close()
