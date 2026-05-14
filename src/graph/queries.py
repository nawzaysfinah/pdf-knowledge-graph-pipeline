"""Cypher query pack registry and output renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    title: str
    description: str
    parameter_schema: dict[str, Any]
    cypher_template: str
    expected_output: str


def build_query_registry() -> dict[str, QuerySpec]:
    """Return the default query pack registry."""
    queries = [
        QuerySpec(
            query_id="cross_division_initiatives",
            title="Cross-division initiatives",
            description="Initiatives linked to multiple divisions through document evidence.",
            parameter_schema={"limit": {"type": "integer", "default": 15, "min": 1, "max": 100}},
            cypher_template="""
                MATCH (i:Initiative)<-[:ABOUT]-(d:Document)-[:CREATED_BY]->(div:Division)
                OPTIONAL MATCH (i)-[:OWNED_BY]->(owner:Division)
                WITH i,
                     collect(DISTINCT div.name) + collect(DISTINCT owner.name) AS division_names,
                     count(DISTINCT d) AS doc_count,
                     collect(DISTINCT d.doc_id)[0..10] AS doc_ids
                WITH i,
                     reduce(acc = [], name IN division_names |
                        CASE
                            WHEN name IS NULL OR trim(name) = '' OR name IN acc THEN acc
                            ELSE acc + name
                        END
                     ) AS divisions,
                     doc_count,
                     doc_ids
                WHERE size(divisions) > 1
                RETURN i.initiative_id AS initiative_id,
                       i.name AS initiative,
                       divisions,
                       size(divisions) AS division_count,
                       doc_count,
                       doc_ids
                ORDER BY division_count DESC, doc_count DESC, initiative
                LIMIT $limit
            """,
            expected_output="table",
        ),
        QuerySpec(
            query_id="shared_learnings_between_divisions",
            title="Shared learnings between divisions",
            description="Division pairs with overlapping learnings captured in documents.",
            parameter_schema={"limit": {"type": "integer", "default": 20, "min": 1, "max": 100}},
            cypher_template="""
                MATCH (d1:Division)<-[:CREATED_BY]-(doc1:Document)-[:CAPTURES]->(l:Learning)<-[:CAPTURES]-(doc2:Document)-[:CREATED_BY]->(d2:Division)
                WHERE elementId(d1) < elementId(d2)
                WITH d1, d2, count(DISTINCT l) AS shared_learnings,
                     collect(DISTINCT l.text)[0..5] AS sample_learnings,
                     collect(DISTINCT doc1.doc_id)[0..5] + collect(DISTINCT doc2.doc_id)[0..5] AS doc_ids
                WHERE shared_learnings > 0
                RETURN d1.name AS division_a,
                       d2.name AS division_b,
                       shared_learnings,
                       sample_learnings,
                       doc_ids
                ORDER BY shared_learnings DESC, division_a, division_b
                LIMIT $limit
            """,
            expected_output="table",
        ),
        QuerySpec(
            query_id="topic_co_occurrence",
            title="Topic co-occurrence",
            description="Top topic pairs appearing in the same documents.",
            parameter_schema={"limit": {"type": "integer", "default": 25, "min": 1, "max": 200}},
            cypher_template="""
                MATCH (d:Document)-[:MENTIONS]->(t:Topic)
                WITH d, collect(DISTINCT t) AS topics
                WHERE size(topics) > 1
                UNWIND range(0, size(topics)-2) AS i
                UNWIND range(i+1, size(topics)-1) AS j
                WITH topics[i] AS t1, topics[j] AS t2, count(*) AS co_count, collect(DISTINCT d.doc_id)[0..10] AS doc_ids
                RETURN t1.name AS topic_a,
                       t2.name AS topic_b,
                       co_count AS count,
                       toFloat(co_count) AS score,
                       doc_ids
                ORDER BY count DESC, topic_a, topic_b
                LIMIT $limit
            """,
            expected_output="graph",
        ),
        QuerySpec(
            query_id="filing_health_by_division_time",
            title="Filing/documentation health",
            description="Document volume and metadata completeness by division and year.",
            parameter_schema={"limit": {"type": "integer", "default": 200, "min": 1, "max": 2000}},
            cypher_template="""
                MATCH (doc:Document)
                OPTIONAL MATCH (doc)-[:CREATED_BY]->(div:Division)
                WITH coalesce(div.name, 'Unknown') AS division,
                     CASE
                         WHEN doc.date IS NULL OR trim(doc.date) = '' THEN 'Unknown'
                         ELSE substring(doc.date, 0, 4)
                     END AS year,
                     doc
                WITH division,
                     year,
                     count(doc) AS doc_count,
                     collect(DISTINCT doc.doc_id)[0..10] AS doc_ids,
                     avg(CASE WHEN doc.title IS NULL OR trim(doc.title) = '' THEN 1.0 ELSE 0.0 END) AS missing_title_rate,
                     avg(CASE WHEN doc.doc_type IS NULL OR trim(doc.doc_type) = '' THEN 1.0 ELSE 0.0 END) AS missing_doc_type_rate,
                     avg(CASE WHEN doc.source_uri IS NULL OR trim(doc.source_uri) = '' THEN 1.0 ELSE 0.0 END) AS missing_source_uri_rate
                RETURN division,
                       year,
                       doc_count,
                       round(missing_title_rate, 3) AS missing_title_rate,
                       round(missing_doc_type_rate, 3) AS missing_doc_type_rate,
                       round(missing_source_uri_rate, 3) AS missing_source_uri_rate,
                       doc_ids
                ORDER BY division, year
                LIMIT $limit
            """,
            expected_output="timeline",
        ),
        QuerySpec(
            query_id="recurring_issues_over_time",
            title="Recurring issues over time",
            description="Issues linked to learnings/initiatives by year.",
            parameter_schema={"limit": {"type": "integer", "default": 100, "min": 1, "max": 1000}},
            cypher_template="""
                MATCH (issue:Issue)
                OPTIONAL MATCH (issue)<-[:ADDRESSES]-(l:Learning)<-[:CAPTURES]-(doc_l:Document)
                OPTIONAL MATCH (issue)<-[:ADDRESSES]-(i:Initiative)<-[:ABOUT]-(doc_i:Document)
                WITH issue,
                     [d IN collect(DISTINCT doc_l) WHERE d IS NOT NULL] + [d IN collect(DISTINCT doc_i) WHERE d IS NOT NULL] AS docs
                UNWIND docs AS doc
                WITH issue,
                     CASE
                         WHEN doc.date IS NULL OR trim(doc.date) = '' THEN 'Unknown'
                         ELSE substring(doc.date, 0, 4)
                     END AS year,
                     doc
                RETURN year,
                       issue.name AS issue,
                       count(DISTINCT doc) AS doc_count,
                       collect(DISTINCT doc.doc_id)[0..10] AS doc_ids
                ORDER BY year, doc_count DESC, issue
                LIMIT $limit
            """,
            expected_output="timeline",
        ),
    ]
    return {spec.query_id: spec for spec in queries}


def run_query_pack(
    client: Any,
    query_registry: dict[str, QuerySpec],
    query_id: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a named query from the query pack."""
    if query_id not in query_registry:
        raise KeyError(f"Unknown query_id: {query_id}")

    spec = query_registry[query_id]
    params = parameters or {}

    for param_name, definition in spec.parameter_schema.items():
        if param_name not in params and "default" in definition:
            params[param_name] = definition["default"]

    return client.run_query(spec.cypher_template, params=params)


def render_list(rows: list[dict[str, Any]], label_key: str, score_key: str) -> list[str]:
    """Render ranked list lines from query rows."""
    output = []
    for idx, row in enumerate(rows, start=1):
        output.append(f"{idx}. {row.get(label_key)} ({row.get(score_key)})")
    return output


def render_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Render query rows as dataframe."""
    return pd.DataFrame(rows)


def render_graph(
    rows: list[dict[str, Any]],
    source_col: str = "topic_a",
    target_col: str = "topic_b",
    weight_col: str = "count",
) -> dict[str, list[dict[str, Any]]]:
    """Render row pairs into lightweight graph structure for agraph."""
    node_ids: set[str] = set()
    edges: list[dict[str, Any]] = []
    for row in rows:
        source = str(row.get(source_col, "")).strip()
        target = str(row.get(target_col, "")).strip()
        if not source or not target:
            continue
        node_ids.add(source)
        node_ids.add(target)
        edges.append(
            {
                "source": source,
                "target": target,
                "label": str(row.get(weight_col, "")),
            }
        )

    nodes = [{"id": node_id, "label": node_id} for node_id in sorted(node_ids)]
    return {"nodes": nodes, "edges": edges}


def render_timeline(
    rows: list[dict[str, Any]],
    x_col: str = "year",
    y_col: str = "doc_count",
    series_col: str | None = "division",
):
    """Render timeline using matplotlib only."""
    frame = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(10, 4))

    if frame.empty:
        ax.set_title("No data")
        return fig

    if series_col and series_col in frame.columns:
        for series_name, group in frame.groupby(series_col):
            ordered = group.sort_values(by=[x_col])
            ax.plot(ordered[x_col], ordered[y_col], marker="o", label=str(series_name))
        ax.legend(loc="best")
    else:
        ordered = frame.sort_values(by=[x_col])
        ax.plot(ordered[x_col], ordered[y_col], marker="o")

    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    ax.set_title(f"{y_col} over {x_col}")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return fig
