from __future__ import annotations

from src.graph.queries import build_query_registry, run_query_pack


class FakeClient:
    def run_query(self, cypher: str, params: dict | None = None):
        assert isinstance(cypher, str)
        assert cypher.strip()
        return [{"ok": True, "params": params or {}}]


def test_query_registry_contains_required_queries() -> None:
    registry = build_query_registry()
    required = {
        "cross_division_initiatives",
        "shared_learnings_between_divisions",
        "topic_co_occurrence",
        "filing_health_by_division_time",
        "recurring_issues_over_time",
    }
    assert required.issubset(set(registry.keys()))


def test_run_query_pack_applies_default_params() -> None:
    registry = build_query_registry()
    rows = run_query_pack(FakeClient(), registry, "cross_division_initiatives", parameters={})
    assert rows[0]["params"]["limit"] == 15
