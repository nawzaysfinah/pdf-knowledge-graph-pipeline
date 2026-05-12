"""Graph explorer page using streamlit-agraph."""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st
from streamlit_agraph import Config as AGraphConfig
from streamlit_agraph import Edge, Node, agraph

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config import load_config
from src.graph.neo4j_client import Neo4jClient


st.set_page_config(page_title="Graph Explorer", layout="wide")
config = load_config()


@st.cache_resource
def get_graph_client() -> Neo4jClient:
    return Neo4jClient(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        database=config.neo4j.database,
    )


def _node_palette(label: str) -> str:
    return {
        "Document": "#4C78A8",
        "Division": "#F58518",
        "Initiative": "#54A24B",
        "Topic": "#E45756",
        "Issue": "#72B7B2",
        "Learning": "#B279A2",
        "Outcome": "#FF9DA6",
    }.get(label, "#9D755D")


def _fetch_entity_options(client: Neo4jClient, label: str) -> list[tuple[str, str]]:
    if label == "Document":
        rows = client.run_query(
            """
            MATCH (n:Document)
            RETURN n.doc_id AS value, coalesce(n.title, n.doc_id) AS label
            ORDER BY label
            LIMIT 300
            """
        )
    else:
        rows = client.run_query(
            f"""
            MATCH (n:{label})
            RETURN coalesce(n.name, n.{label.lower()}_id) AS value, coalesce(n.name, n.{label.lower()}_id) AS label
            ORDER BY label
            LIMIT 300
            """
        )
    return [(row["value"], row["label"]) for row in rows if row.get("value")]


def _fetch_subgraph(client: Neo4jClient, label: str, value: str, depth: int) -> dict:
    if label == "Document":
        where_clause = "seed.doc_id = $value"
    else:
        where_clause = "seed.name = $value"

    query = f"""
    MATCH (seed:{label})
    WHERE {where_clause}
    OPTIONAL MATCH p=(seed)-[*1..{depth}]-(nbr)
    WITH collect(DISTINCT seed) + collect(DISTINCT nbr) AS node_list,
         collect(DISTINCT p) AS paths
    UNWIND node_list AS n
    WITH collect(DISTINCT n) AS nodes, [p IN paths WHERE p IS NOT NULL] AS valid_paths
    WITH nodes, reduce(rel_acc = [], p IN valid_paths | rel_acc + relationships(p)) AS rel_flat
    UNWIND CASE WHEN size(rel_flat) = 0 THEN [NULL] ELSE rel_flat END AS rel
    WITH nodes, collect(DISTINCT rel) AS rels
    RETURN
      [n IN nodes | {{
          element_id: elementId(n),
          labels: labels(n),
          props: properties(n)
      }}] AS nodes,
      [r IN rels WHERE r IS NOT NULL | {{
          type: type(r),
          start: elementId(startNode(r)),
          end: elementId(endNode(r)),
          props: properties(r)
      }}] AS relationships
    """

    result = client.run_query(query, params={"value": value})
    if not result:
        return {"nodes": [], "relationships": []}
    return result[0]


st.title("Graph Explorer")
st.caption("Browse local subgraphs with depth 1-2 using Streamlit + streamlit-agraph")

try:
    client = get_graph_client()
    entity_type = st.selectbox("Search Type", ["Initiative", "Topic", "Division", "Document"])
    options = _fetch_entity_options(client, entity_type)

    if not options:
        st.info("No entities found for this type.")
        st.stop()

    selected_value = st.selectbox(
        "Select Entity",
        options=[value for value, _ in options],
        format_func=lambda x: dict(options).get(x, x),
    )
    depth = st.slider("Expand neighbors depth", min_value=1, max_value=2, value=1)
    highlight = st.checkbox("Highlight evidence path from last Ask Anything query", value=True)

    if st.button("Render Subgraph"):
        subgraph = _fetch_subgraph(client, entity_type, selected_value, depth)
        nodes_raw = subgraph.get("nodes", [])
        rels_raw = subgraph.get("relationships", [])

        evidence_pairs = set()
        if highlight:
            for pair in st.session_state.get("last_evidence_graph_pairs", []):
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    evidence_pairs.add((str(pair[0]), str(pair[1])))
                    evidence_pairs.add((str(pair[1]), str(pair[0])))

        node_map: dict[str, dict] = {}
        for item in nodes_raw:
            labels = item.get("labels", [])
            label = labels[0] if labels else "Unknown"
            props = item.get("props", {})
            display = (
                props.get("name")
                or props.get("title")
                or props.get("doc_id")
                or props.get("learning_id")
                or props.get("issue_id")
                or props.get("topic_id")
                or item.get("element_id")
            )
            node_map[item.get("element_id")] = {
                "label": str(display),
                "group": label,
                "color": _node_palette(label),
            }

        nodes = [
            Node(
                id=node_id,
                label=node_info["label"],
                size=18,
                shape="dot",
                color=node_info["color"],
            )
            for node_id, node_info in node_map.items()
        ]

        edges = []
        for rel in rels_raw:
            start = rel.get("start")
            end = rel.get("end")
            if start not in node_map or end not in node_map:
                continue
            start_label = node_map[start]["label"]
            end_label = node_map[end]["label"]
            is_evidence = (start_label, end_label) in evidence_pairs
            edges.append(
                Edge(
                    source=start,
                    target=end,
                    label=str(rel.get("type", "")),
                    color="#C00000" if is_evidence else "#888888",
                )
            )

        if not nodes:
            st.info("No subgraph found for selection.")
        else:
            agraph(
                nodes=nodes,
                edges=edges,
                config=AGraphConfig(
                    directed=True,
                    physics=True,
                    hierarchical=False,
                    width="100%",
                    height=700,
                    nodeHighlightBehavior=True,
                    highlightColor="#F5A623",
                ),
            )

except Exception as exc:  # pragma: no cover - streamlit runtime
    st.error(f"Graph explorer failed: {exc}")
