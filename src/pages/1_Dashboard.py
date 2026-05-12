"""Dashboard page for cross-division insight and filing health."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config import load_config
from src.graph.neo4j_client import Neo4jClient
from src.graph.queries import (
    build_query_registry,
    render_table,
    render_timeline,
    run_query_pack,
)


st.set_page_config(page_title="Dashboard", layout="wide")
config = load_config()


@st.cache_resource
def get_graph_client() -> Neo4jClient:
    return Neo4jClient(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        database=config.neo4j.database,
    )


registry = build_query_registry()
st.title("Dashboard")

try:
    client = get_graph_client()
    counts = client.run_query(
        """
        CALL {
            MATCH (n:Document) RETURN count(n) AS total_documents
        }
        CALL {
            MATCH (n:Division) RETURN count(n) AS total_divisions
        }
        CALL {
            MATCH (n:Initiative) RETURN count(n) AS total_initiatives
        }
        CALL {
            MATCH (n:Topic) RETURN count(n) AS total_topics
        }
        CALL {
            MATCH (n:Issue) RETURN count(n) AS total_issues
        }
        CALL {
            MATCH (n:Learning) RETURN count(n) AS total_learnings
        }
        RETURN total_documents, total_divisions, total_initiatives,
               total_topics, total_issues, total_learnings
        """
    )[0]

    metric_cols = st.columns(6)
    metric_cols[0].metric("Documents", counts["total_documents"])
    metric_cols[1].metric("Divisions", counts["total_divisions"])
    metric_cols[2].metric("Initiatives", counts["total_initiatives"])
    metric_cols[3].metric("Topics", counts["total_topics"])
    metric_cols[4].metric("Issues", counts["total_issues"])
    metric_cols[5].metric("Learnings", counts["total_learnings"])

    st.divider()
    left, right = st.columns((1, 1))

    with left:
        st.subheader("Cross-division Initiatives")
        cross_rows = run_query_pack(client, registry, "cross_division_initiatives", {"limit": 15})
        st.dataframe(render_table(cross_rows), use_container_width=True)

        st.subheader("Recurring Issues Over Time")
        issue_rows = run_query_pack(client, registry, "recurring_issues_over_time", {"limit": 60})
        st.dataframe(pd.DataFrame(issue_rows), use_container_width=True)

    with right:
        st.subheader("Filing Health by Division / Year")
        filing_rows = run_query_pack(client, registry, "filing_health_by_division_time", {"limit": 500})
        st.dataframe(render_table(filing_rows), use_container_width=True)
        st.pyplot(render_timeline(filing_rows, x_col="year", y_col="doc_count", series_col="division"))

        st.subheader("Top Topics by Volume")
        topic_rows = client.run_query(
            """
            MATCH (doc:Document)-[:MENTIONS]->(t:Topic)
            RETURN t.name AS topic, count(DISTINCT doc) AS doc_count
            ORDER BY doc_count DESC, topic
            LIMIT 15
            """
        )
        st.dataframe(pd.DataFrame(topic_rows), use_container_width=True)

except Exception as exc:  # pragma: no cover - streamlit runtime
    st.error(f"Dashboard failed to load Neo4j data: {exc}")
