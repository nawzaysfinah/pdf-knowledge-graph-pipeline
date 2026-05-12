"""Evidence object helpers for traceable Graph-RAG responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _derive_nodes_edges(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(node_type: str, value: str) -> None:
        key = f"{node_type}:{value}"
        nodes_map[key] = {"id": key, "type": node_type, "label": value}

    for row in rows:
        initiative = row.get("initiative")
        issue = row.get("issue")
        division_a = row.get("division_a")
        division_b = row.get("division_b")
        topic_a = row.get("topic_a")
        topic_b = row.get("topic_b")

        if initiative:
            add_node("Initiative", str(initiative))
        if issue:
            add_node("Issue", str(issue))
        if topic_a:
            add_node("Topic", str(topic_a))
        if topic_b:
            add_node("Topic", str(topic_b))
            edges.append(
                {
                    "source": f"Topic:{topic_a}",
                    "target": f"Topic:{topic_b}",
                    "type": "CO_OCCURS_WITH",
                }
            )
        if division_a:
            add_node("Division", str(division_a))
        if division_b:
            add_node("Division", str(division_b))
            edges.append(
                {
                    "source": f"Division:{division_a}",
                    "target": f"Division:{division_b}",
                    "type": "SHARES_LEARNING_WITH",
                }
            )
        for division in row.get("divisions", []) or []:
            add_node("Division", str(division))

        for doc_id in row.get("doc_ids", []) or []:
            add_node("Document", str(doc_id))

    return list(nodes_map.values()), edges


def build_evidence_payload(
    query_id: str,
    parameters: dict[str, Any],
    rows: list[dict[str, Any]],
    rationale: str,
    documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a normalized evidence payload."""
    docs = documents or []
    nodes, edges = _derive_nodes_edges(rows)
    doc_nodes = {node["label"] for node in nodes if node.get("type") == "Document"}
    known_doc_ids = {str(doc.get("doc_id")) for doc in docs}
    for doc_id in sorted(doc_nodes):
        if doc_id not in known_doc_ids:
            docs.append({"doc_id": doc_id, "title": "", "date": ""})

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query_id": query_id,
        "parameters": parameters,
        "row_count": len(rows),
        "rows": rows,
        "nodes": nodes,
        "edges": edges,
        "documents": docs,
        "why_these_results": rationale,
    }


def evidence_is_empty(evidence: dict[str, Any]) -> bool:
    """Check whether evidence has no graph-backed rows."""
    return int(evidence.get("row_count", 0)) == 0
