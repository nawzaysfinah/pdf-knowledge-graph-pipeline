"""Insights report generator page."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config import load_config
from src.graph.neo4j_client import Neo4jClient
from src.graph.queries import build_query_registry, run_query_pack


st.set_page_config(page_title="Insights Report", layout="wide")
config = load_config()
registry = build_query_registry()


@st.cache_resource
def get_graph_client() -> Neo4jClient:
    return Neo4jClient(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        database=config.neo4j.database,
    )


def _query_sections(client: Neo4jClient) -> list[tuple[str, list[dict]]]:
    ordered = [
        "cross_division_initiatives",
        "shared_learnings_between_divisions",
        "topic_co_occurrence",
        "filing_health_by_division_time",
        "recurring_issues_over_time",
    ]
    sections: list[tuple[str, list[dict]]] = []
    for query_id in ordered:
        rows = run_query_pack(client, registry, query_id, {"limit": 20})
        sections.append((query_id, rows))
    return sections


st.title("Insights Report")
st.caption("Generate a markdown insights brief grounded in graph evidence")

if st.button("Generate report"):
    try:
        client = get_graph_client()
        sections = _query_sections(client)

        lines = [
            "# Agency KG Insights Report",
            "",
            f"Generated at: {datetime.utcnow().isoformat()}Z",
            "",
            "## Top Insights",
            "",
        ]

        for query_id, rows in sections:
            spec = registry[query_id]
            lines.append(f"### {spec.title}")
            lines.append(spec.description)
            lines.append("")

            if rows:
                df = pd.DataFrame(rows)
                lines.append(df.to_markdown(index=False))
            else:
                lines.append("No grounded evidence returned for this section.")
            lines.append("")

        lines.extend(
            [
                "## Gaps and Recommendations",
                "- Expand metadata completeness for title/doc_type/source_uri where missing rates are high.",
                "- Increase cross-division tagging consistency for stronger initiative attribution.",
                "- Continue human review for extracted triples before graph write-back.",
                "",
                "## Limitations",
                "- Findings are bounded by loaded canonical datasets and approved extracted triples.",
                "- No external sources are used (fully offline design).",
                "",
                "## Next Steps",
                "- Add additional domain-specific Cypher queries for policy and operational drill-down.",
                "- Tune extraction prompt templates with agency-specific vocabulary and labels.",
            ]
        )

        report_text = "\n".join(lines)
        config.paths.reports_dir.mkdir(parents=True, exist_ok=True)
        filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = config.paths.reports_dir / filename
        report_path.write_text(report_text, encoding="utf-8")

        st.success(f"Report written to {report_path}")
        st.markdown(report_text)

    except Exception as exc:  # pragma: no cover - streamlit runtime
        st.error(f"Failed to generate report: {exc}")
