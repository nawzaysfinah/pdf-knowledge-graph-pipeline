"""NEA Knowledge Graph — Chat Interface.

Natural language → Cypher → grounded answer via local Ollama (qwen3:latest).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config import load_config
from src.graph.neo4j_client import Neo4jClient
from src.llm.nl_to_cypher import NLToCypherEngine

st.set_page_config(page_title="Ask the Knowledge Graph", layout="wide")

config = load_config()


@st.cache_resource
def get_engine() -> NLToCypherEngine:
    client = Neo4jClient(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        database=config.neo4j.database,
    )
    return NLToCypherEngine(client, config.ollama.base_url)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []   # {role, content, cypher, results, error}

if "history" not in st.session_state:
    st.session_state.history = []    # {question, cypher, answer} for LLM context


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("NEA Knowledge Graph")
    st.caption("Chat powered by qwen3:latest + Neo4j")

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.history = []
        st.rerun()

    st.divider()
    st.markdown("**Graph stats**")
    try:
        engine = get_engine()
        stats = engine.graph_client.run_query(
            "MATCH (n) RETURN count(n) AS nodes "
            "UNION ALL MATCH ()-[r]->() RETURN count(r) AS nodes"
        )
        if len(stats) >= 2:
            st.metric("Nodes", f"{stats[0]['nodes']:,}")
            st.metric("Relationships", f"{stats[1]['nodes']:,}")
    except Exception:
        st.warning("Neo4j unreachable")

    st.divider()
    st.markdown("**Example questions**")
    examples = [
        "What programmes does NEA operate?",
        "Who heads NEA?",
        "Which organisations collaborate with NEA?",
        "What pollutants are emitted and by whom?",
        "What targets has NEA set for waste reduction?",
        "Show me the most connected entities",
        "Which facilities are located in Singapore?",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True, key=f"ex_{ex[:20]}"):
            st.session_state._prefill = ex
            st.rerun()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("Ask the Knowledge Graph")
st.caption(
    "Ask questions in plain English. The graph contains entities and relationships "
    "extracted from NEA annual reports and sustainability reports."
)

# ---------------------------------------------------------------------------
# Render existing messages
# ---------------------------------------------------------------------------

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg["role"] == "assistant":
            cypher = msg.get("cypher", "")
            results = msg.get("results", [])
            error = msg.get("error")

            if error and not results:
                st.error(f"Query error: {error}")

            if cypher:
                with st.expander("Cypher query", expanded=False):
                    st.code(cypher, language="cypher")

            if results:
                with st.expander(f"Results ({len(results)} rows)", expanded=False):
                    df = pd.DataFrame(results)
                    st.dataframe(df, use_container_width=True)

                    # Show evidence if present
                    evidence_rows = [
                        r for r in results
                        if r.get("evidence") and str(r["evidence"]).strip()
                    ]
                    if evidence_rows:
                        st.markdown("**Source evidence:**")
                        for ev in evidence_rows[:10]:
                            doc = ev.get("source_doc", ev.get("r.source_doc", ""))
                            page = ev.get("source_page", ev.get("r.source_page", ""))
                            text = ev.get("evidence", ev.get("r.evidence", ""))
                            loc = f" — {doc} p.{page}" if doc else ""
                            st.caption(f'"{text}"{loc}')


# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

prefill = st.session_state.pop("_prefill", None)
prompt = st.chat_input("Ask anything about NEA…") or prefill

if prompt:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Querying knowledge graph…"):
            try:
                engine = get_engine()
                result = engine.ask(prompt, history=st.session_state.history)
            except Exception as exc:
                result = {
                    "question": prompt,
                    "cypher": "",
                    "results": [],
                    "answer": f"Something went wrong: {exc}",
                    "error": str(exc),
                }

        answer  = result["answer"]
        cypher  = result.get("cypher", "")
        results = result.get("results", [])
        error   = result.get("error")

        st.markdown(answer)

        if error and not results:
            st.error(f"Query error: {error}")

        if cypher:
            with st.expander("Cypher query", expanded=False):
                st.code(cypher, language="cypher")

        if results:
            with st.expander(f"Results ({len(results)} rows)", expanded=False):
                df = pd.DataFrame(results)
                st.dataframe(df, use_container_width=True)

                evidence_rows = [
                    r for r in results
                    if r.get("evidence") and str(r["evidence"]).strip()
                ]
                if evidence_rows:
                    st.markdown("**Source evidence:**")
                    for ev in evidence_rows[:10]:
                        doc = ev.get("source_doc", ev.get("r.source_doc", ""))
                        page = ev.get("source_page", ev.get("r.source_page", ""))
                        text = ev.get("evidence", ev.get("r.evidence", ""))
                        loc = f" — {doc} p.{page}" if doc else ""
                        st.caption(f'"{text}"{loc}')

    # Persist to session state
    st.session_state.messages.append({
        "role":    "assistant",
        "content": answer,
        "cypher":  cypher,
        "results": results,
        "error":   error,
    })
    st.session_state.history.append({
        "question": prompt,
        "cypher":   cypher,
        "answer":   answer,
    })
