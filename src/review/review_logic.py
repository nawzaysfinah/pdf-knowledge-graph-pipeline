"""Business logic for approving/rejecting extracted triples."""

from __future__ import annotations

from typing import Any

from src.graph.loader import GraphLoader
from src.review.review_store import ReviewStore


class ReviewService:
    """Coordinates review outcomes and graph writes."""

    def __init__(self, review_store: ReviewStore, graph_loader: GraphLoader) -> None:
        self.review_store = review_store
        self.graph_loader = graph_loader

    def approve(
        self,
        pending_id: int,
        reviewer: str,
        edited_payload: dict[str, Any] | None = None,
        notes: str = "",
    ) -> None:
        """Approve a pending extraction and persist to graph."""
        payload = edited_payload
        if payload is None:
            payload = self.review_store.get_pending(pending_id)
            if payload is None:
                raise ValueError(f"Pending id not found: {pending_id}")

        if edited_payload is not None:
            self.review_store.update_pending_payload(pending_id, edited_payload)

        self.graph_loader.upsert_extraction_payload(payload)
        self.review_store.record_review(
            pending_id=pending_id,
            reviewer=reviewer,
            action="APPROVE",
            notes=notes,
            edited_payload=edited_payload,
        )

    def reject(
        self,
        pending_id: int,
        reviewer: str,
        notes: str = "",
    ) -> None:
        """Reject a pending extraction while preserving audit trail."""
        self.review_store.record_review(
            pending_id=pending_id,
            reviewer=reviewer,
            action="REJECT",
            notes=notes,
            edited_payload=None,
        )
