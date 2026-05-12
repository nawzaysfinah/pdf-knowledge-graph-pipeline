"""Evidence-first Graph-RAG orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

from src.graph.evidence import build_evidence_payload, evidence_is_empty
from src.graph.neo4j_client import Neo4jClient
from src.graph.queries import QuerySpec, run_query_pack
from src.llm.ollama_client import OllamaClient


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    query_id: str
    rationale: str


class GraphRAGEngine:
    """Question routing, evidence retrieval, and grounded narrative generation."""

    def __init__(
        self,
        graph_client: Neo4jClient,
        ollama_client: OllamaClient,
        query_registry: dict[str, QuerySpec],
    ) -> None:
        self.graph_client = graph_client
        self.ollama_client = ollama_client
        self.query_registry = query_registry

    def route_question(self, question: str) -> RouteDecision:
        """Route question into a query-pack intent."""
        q = question.lower()
        if any(token in q for token in ["cross", "across division", "multi-division", "between division"]):
            return RouteDecision(
                intent="cross-division",
                query_id="cross_division_initiatives",
                rationale="Question asks for initiatives spanning multiple divisions.",
            )
        if "shared learning" in q or "shared learnings" in q:
            return RouteDecision(
                intent="shared-learnings",
                query_id="shared_learnings_between_divisions",
                rationale="Question asks for overlap of learnings across divisions.",
            )
        if "co-occur" in q or "co occur" in q or "topic" in q:
            return RouteDecision(
                intent="topic-cooccurrence",
                query_id="topic_co_occurrence",
                rationale="Question centers on topic relationships and co-occurrence.",
            )
        if "filing" in q or "metadata" in q or "documentation" in q or "gap" in q:
            return RouteDecision(
                intent="filing-health",
                query_id="filing_health_by_division_time",
                rationale="Question asks about filing completeness and metadata gaps.",
            )
        if "issue" in q or "trend" in q or "over time" in q:
            return RouteDecision(
                intent="issues-trend",
                query_id="recurring_issues_over_time",
                rationale="Question asks for recurring issues and temporal trend.",
            )

        return RouteDecision(
            intent="general-explore",
            query_id="topic_co_occurrence",
            rationale="Defaulted to broad exploration via topic co-occurrence.",
        )

    def infer_parameters(self, question: str, query_id: str) -> dict[str, Any]:
        """Infer basic parameters from question text."""
        params: dict[str, Any] = {}
        numbers = re.findall(r"\b(\d{1,3})\b", question)
        if numbers:
            candidate = int(numbers[0])
            if 1 <= candidate <= 500:
                params["limit"] = candidate

        defaults = self.query_registry[query_id].parameter_schema
        for name, definition in defaults.items():
            params.setdefault(name, definition.get("default"))
        return params

    def retrieve_evidence(self, question: str) -> tuple[RouteDecision, dict[str, Any]]:
        """Run retrieval and package traceable evidence."""
        route = self.route_question(question)
        params = self.infer_parameters(question, route.query_id)
        rows = run_query_pack(
            client=self.graph_client,
            query_registry=self.query_registry,
            query_id=route.query_id,
            parameters=params,
        )

        doc_ids: set[str] = set()
        for row in rows:
            if row.get("doc_id"):
                doc_ids.add(str(row.get("doc_id")))
            for doc_id in row.get("doc_ids", []) or []:
                if doc_id:
                    doc_ids.add(str(doc_id))

        documents: list[dict[str, Any]] = []
        if doc_ids:
            documents = self.graph_client.run_query(
                """
                MATCH (d:Document)
                WHERE d.doc_id IN $doc_ids
                RETURN d.doc_id AS doc_id, d.title AS title, d.date AS date
                ORDER BY d.doc_id
                """,
                params={"doc_ids": sorted(doc_ids)},
            )

        evidence = build_evidence_payload(
            query_id=route.query_id,
            parameters=params,
            rows=rows,
            rationale=route.rationale,
            documents=documents,
        )
        return route, evidence

    def generate_answer_from_evidence(
        self,
        question: str,
        evidence: dict[str, Any],
        allow_bounded_inference: bool = False,
    ) -> str:
        """Generate narrative answer only from provided evidence."""
        if evidence_is_empty(evidence):
            return "I don't know based on the knowledge graph."

        inference_instruction = (
            "You may include bounded inference only if explicitly labeled as inference."
            if allow_bounded_inference
            else "Do not infer beyond evidence. If uncertain, say you cannot conclude."
        )

        prompt = f"""
You are answering a question strictly using graph evidence JSON.
Never invent documents, entities, relationships, or counts.
{inference_instruction}
If evidence does not support an answer, output exactly: I don't know based on the knowledge graph.

Question:
{question}

Evidence JSON:
{json.dumps(evidence, indent=2)}

Return a concise response with:
1) direct answer
2) short grounding summary
""".strip()

        response = self.ollama_client.generate(prompt, json_mode=False, temperature=0.1).strip()
        return response or "I don't know based on the knowledge graph."

    def ask(self, question: str, allow_bounded_inference: bool = False) -> dict[str, Any]:
        """Full evidence-first Graph-RAG response."""
        route, evidence = self.retrieve_evidence(question)
        answer = self.generate_answer_from_evidence(
            question=question,
            evidence=evidence,
            allow_bounded_inference=allow_bounded_inference,
        )
        return {
            "intent": route.intent,
            "query_id": route.query_id,
            "parameters": evidence.get("parameters", {}),
            "evidence": evidence,
            "answer": answer,
        }
