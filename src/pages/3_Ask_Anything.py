"""Evidence-first Graph-RAG chat page."""

from __future__ import annotations

from pathlib import Path
import json
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config import load_config
from src.graph.neo4j_client import Neo4jClient
from src.graph.queries import build_query_registry
from src.llm.ollama_client import OllamaClient
from src.llm.rag import GraphRAGEngine


st.set_page_config(page_title="Ask Anything", layout="wide")
config = load_config()


@st.cache_resource
def get_graph_client() -> Neo4jClient:
    return Neo4jClient(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        database=config.neo4j.database,
    )


@st.cache_resource
def get_ollama_client() -> OllamaClient:
    return OllamaClient(config.ollama.base_url, config.ollama.model)


@st.cache_resource
def get_engine() -> GraphRAGEngine:
    return GraphRAGEngine(
        graph_client=get_graph_client(),
        ollama_client=get_ollama_client(),
        query_registry=build_query_registry(),
    )


st.title("Ask Anything")
st.caption("Graph-RAG with strict evidence-first traceability")

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "last_evidence" not in st.session_state:
    st.session_state["last_evidence"] = None
if "last_question" not in st.session_state:
    st.session_state["last_question"] = ""

allow_inference = st.toggle("Allow bounded inference", value=False)

st.subheader("Evidence")
last_evidence = st.session_state.get("last_evidence")
if last_evidence:
    st.write(f"Query ID: `{last_evidence.get('query_id')}`")
    st.write(f"Why these results: {last_evidence.get('why_these_results')}")
    rows = last_evidence.get("rows", [])
    nodes = last_evidence.get("nodes", [])
    edges = last_evidence.get("edges", [])
    documents = last_evidence.get("documents", [])

    with st.expander("Evidence: Nodes", expanded=True):
        st.dataframe(pd.DataFrame(nodes), use_container_width=True)
    with st.expander("Evidence: Edges", expanded=True):
        st.dataframe(pd.DataFrame(edges), use_container_width=True)
    with st.expander("Evidence: Documents", expanded=True):
        st.dataframe(pd.DataFrame(documents), use_container_width=True)
    with st.expander("Evidence: Query Rows", expanded=True):
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.download_button(
        label="Download evidence (JSON)",
        data=json.dumps(last_evidence, indent=2),
        file_name="evidence.json",
        mime="application/json",
    )
else:
    st.info("No evidence yet. Ask a question to retrieve graph-backed evidence.")

question = st.text_input(
    "Question",
    placeholder="Example: Which initiatives are active across multiple divisions?",
)

if st.button("Ask") and question.strip():
    try:
        engine = get_engine()
        result = engine.ask(question=question.strip(), allow_bounded_inference=allow_inference)
        evidence = result["evidence"]

        st.session_state["last_question"] = question.strip()
        st.session_state["last_evidence"] = evidence
        st.session_state["chat_history"].append(
            {
                "question": question.strip(),
                "answer": result["answer"],
                "query_id": result["query_id"],
                "evidence": evidence,
            }
        )

        pairs = []
        for row in evidence.get("rows", []):
            a = row.get("topic_a")
            b = row.get("topic_b")
            if a and b:
                pairs.append((a, b))
        st.session_state["last_evidence_graph_pairs"] = pairs

        st.rerun()
    except Exception as exc:  # pragma: no cover - streamlit runtime
        st.error(f"Failed to answer question: {exc}")

if st.button("Regenerate narrative (same evidence)"):
    evidence = st.session_state.get("last_evidence")
    last_question = st.session_state.get("last_question", "")
    if not evidence or not last_question:
        st.warning("No prior evidence to regenerate from.")
    else:
        try:
            engine = get_engine()
            regenerated = engine.generate_answer_from_evidence(
                question=last_question,
                evidence=evidence,
                allow_bounded_inference=allow_inference,
            )
            st.session_state["chat_history"].append(
                {
                    "question": last_question,
                    "answer": regenerated,
                    "query_id": evidence.get("query_id", ""),
                    "evidence": evidence,
                }
            )
            st.rerun()
        except Exception as exc:  # pragma: no cover - streamlit runtime
            st.error(f"Regenerate failed: {exc}")

st.divider()
st.subheader("Chat History")
if not st.session_state["chat_history"]:
    st.write("No messages yet.")
else:
    for idx, item in enumerate(reversed(st.session_state["chat_history"]), start=1):
        st.markdown(f"**Q{idx}:** {item['question']}")
        st.markdown(f"**Evidence Query:** `{item['query_id']}`")
        st.markdown(f"**A{idx}:** {item['answer']}")
        st.caption("Evidence rows: " + str(item["evidence"].get("row_count", 0)))
        st.divider()
