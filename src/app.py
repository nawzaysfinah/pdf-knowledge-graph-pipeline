"""Streamlit entrypoint for the offline agency KG prototype."""

from __future__ import annotations

from pathlib import Path
import json
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.config import load_config
from src.graph.loader import GraphLoader
from src.graph.neo4j_client import Neo4jClient
from src.io.canonicalize import run_canonicalization
from src.io.validate import validate_canonical
from src.llm.extract_triples import extract_triples_for_document
from src.llm.ollama_client import OllamaClient
from src.logging_utils import configure_logging, get_logger
from src.review.review_logic import ReviewService
from src.review.review_store import ReviewStore


st.set_page_config(page_title="Agency KG Prototype", layout="wide")

config = load_config()
configure_logging(config.log_level)
logger = get_logger(__name__)


@st.cache_resource
def get_graph_client() -> Neo4jClient:
    return Neo4jClient(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        database=config.neo4j.database,
    )


@st.cache_resource
def get_review_store() -> ReviewStore:
    return ReviewStore(config.paths.review_db)


def _safe_graph_loader() -> GraphLoader | None:
    try:
        return GraphLoader(get_graph_client())
    except Exception as exc:  # pragma: no cover - streamlit runtime path
        st.error(f"Neo4j not available: {exc}")
        return None


def _canonical_docs_path() -> Path:
    return config.paths.data_canonical / "canonical_documents.csv"


st.title("AI-Enabled Knowledge Graph & Graph-RAG Prototype (Offline)")
st.caption("Evidence-first prototype for agency findability and organizational insight")

with st.sidebar:
    st.header("Runtime")
    st.write(f"Neo4j URI: `{config.neo4j.uri}`")
    st.write(f"Ollama Model: `{config.ollama.model}`")
    st.write(f"Mapping Config: `{config.paths.mapping_config}`")
    st.write("Use pages for Dashboard, Graph Explorer, Ask Anything, and Insights Report.")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("1) Canonicalize + Validate", use_container_width=True):
        summary = run_canonicalization(config)
        report = validate_canonical(config.paths.data_canonical)
        st.success("Canonicalization completed")
        st.json(summary)
        st.json(report)

with col2:
    if st.button("2) Load Canonical to Neo4j", use_container_width=True):
        loader = _safe_graph_loader()
        if loader is not None:
            try:
                loader.ensure_schema(config.paths.neo4j_constraints, config.paths.neo4j_indexes)
                stats = loader.load_canonical(config.paths.data_canonical)
                loader.apply_postcompute(config.paths.neo4j_postcompute)
                st.success("Neo4j load completed")
                st.json(stats)
            except Exception as exc:  # pragma: no cover - runtime path
                logger.exception("Failed to load canonical data")
                st.error(f"Load failed: {exc}")

with col3:
    max_docs = st.number_input(
        "Docs to extract",
        min_value=1,
        max_value=500,
        value=30,
        step=1,
    )
    if st.button("3) Extract Triples to Review Queue", use_container_width=True):
        doc_path = _canonical_docs_path()
        if not doc_path.exists():
            st.error("Run canonicalization first. canonical_documents.csv not found.")
        else:
            docs_df = pd.read_csv(doc_path, dtype=str, keep_default_na=False).head(int(max_docs))
            ollama = OllamaClient(config.ollama.base_url, config.ollama.model)
            review_store = get_review_store()
            progress = st.progress(0)
            inserted = 0
            failures: list[str] = []

            for idx, row in docs_df.iterrows():
                doc_id = str(row.get("doc_id", "")).strip()
                text = str(row.get("text", "")).strip()
                if not doc_id or not text:
                    continue
                try:
                    payload = extract_triples_for_document(ollama_client=ollama, doc_id=doc_id, text=text)
                    review_store.enqueue_extraction(payload)
                    inserted += 1
                except Exception as exc:  # pragma: no cover - runtime path
                    failures.append(f"{doc_id}: {exc}")
                progress.progress((idx + 1) / max(len(docs_df), 1))

            st.success(f"Queued {inserted} extraction(s) for review")
            if failures:
                st.warning("Some extractions failed")
                st.code("\n".join(failures[:20]))

st.divider()
st.subheader("Human-in-the-loop Triple Review")
reviewer = st.text_input("Reviewer", value="demo_reviewer")
review_notes = st.text_input("Review Notes (optional)", value="")

store = get_review_store()
pending_grouped = store.list_pending_grouped_by_doc()
st.write(f"Pending items: **{sum(len(v) for v in pending_grouped.values())}**")

if not pending_grouped:
    st.info("No pending triples. Run extraction to populate review queue.")
else:
    loader = _safe_graph_loader()
    if loader is None:
        st.warning("Neo4j connection required for approvals.")
    else:
        review_service = ReviewService(store, loader)
        for doc_id, items in pending_grouped.items():
            with st.expander(f"Document {doc_id} ({len(items)} pending)"):
                for item in items:
                    pending_id = item["_meta"]["pending_id"]
                    st.caption(
                        f"Pending ID: {pending_id} | created: {item['_meta']['created_at']} | status: {item['_meta']['status']}"
                    )
                    editor_key = f"payload_editor_{pending_id}"
                    default_json = json.dumps(
                        {
                            "doc_id": item.get("doc_id"),
                            "entities": item.get("entities", {}),
                            "relations": item.get("relations", []),
                            "confidence": item.get("confidence", {}),
                        },
                        indent=2,
                    )
                    edited_json = st.text_area(
                        f"Edit payload for pending {pending_id}",
                        value=default_json,
                        height=240,
                        key=editor_key,
                    )

                    action_cols = st.columns(2)
                    with action_cols[0]:
                        if st.button("Approve", key=f"approve_{pending_id}", use_container_width=True):
                            try:
                                edited_payload = json.loads(edited_json)
                                review_service.approve(
                                    pending_id=pending_id,
                                    reviewer=reviewer,
                                    edited_payload=edited_payload,
                                    notes=review_notes,
                                )
                                st.success(f"Approved pending {pending_id}")
                                st.rerun()
                            except Exception as exc:  # pragma: no cover - runtime path
                                st.error(f"Approve failed: {exc}")

                    with action_cols[1]:
                        if st.button("Reject", key=f"reject_{pending_id}", use_container_width=True):
                            try:
                                review_service.reject(
                                    pending_id=pending_id,
                                    reviewer=reviewer,
                                    notes=review_notes,
                                )
                                st.warning(f"Rejected pending {pending_id}")
                                st.rerun()
                            except Exception as exc:  # pragma: no cover - runtime path
                                st.error(f"Reject failed: {exc}")
