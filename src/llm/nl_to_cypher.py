"""NL-to-Cypher engine for the NEA knowledge graph.

Two-pass pipeline:
  1. Ollama (qwen3:latest) translates the question + conversation history → Cypher
  2. Neo4j executes the Cypher
  3. Ollama synthesises a grounded natural-language answer from the results
"""
from __future__ import annotations

import os
import re
from typing import Any

from src.graph.neo4j_client import Neo4jClient
from src.llm.ollama_client import OllamaClient

CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:latest")

# ---------------------------------------------------------------------------
# Schema context injected into every prompt
# ---------------------------------------------------------------------------

_ENTITY_TYPES = (
    "GovernmentAgency, Regulation, Policy, Programme, Pollutant, WasteType, "
    "Facility, Organisation, Person, EnvironmentalIndicator, ClimateEvent, "
    "GeographicArea, Standard, Technology, Disease, Vector, DateOrPeriod, Metric"
)

_PREDICATES = (
    "REGULATES, ENFORCES, IMPLEMENTS, OPERATES, LOCATED_IN, TARGETS, MEASURES, "
    "SET_TARGET, EMITS, TREATS_OR_PROCESSES, CAUSES, TRANSMITS, AFFECTS, "
    "COLLABORATES_WITH, FUNDED_BY, SUCCEEDED_BY, COMPLIES_WITH, ACHIEVED_METRIC, "
    "OCCURRED_DURING, HEADED_BY"
)

_SCHEMA_BLOCK = f"""
GRAPH SCHEMA
============
Nodes: (:Entity) with property `name` (string), `type` (one of: {_ENTITY_TYPES}), `aliases` (list).
All nodes also have a second label matching their type, e.g. :Entity:Programme.

Relationships between (:Entity) nodes. Core predicates: {_PREDICATES}
(many other predicates also exist for extended relationships).

Key relationship properties: confidence (float), evidence (string quote from source), source_doc (filename), source_page (int).
""".strip()

_FEW_SHOT = """
EXAMPLES
========
Q: What programmes does NEA operate?
MATCH (n:Entity)-[r:OPERATES]->(m:Entity)
WHERE n.name CONTAINS "Environment Agency" OR n.name = "NEA"
RETURN m.name AS programme, m.type, r.evidence LIMIT 25

Q: Who heads NEA?
MATCH (p:Entity)-[r:HEADED_BY]->(n:Entity)
WHERE n.name CONTAINS "Environment Agency"
RETURN p.name, p.type, r.evidence LIMIT 10

Q: What regulations does NEA enforce or regulate?
MATCH (n:Entity)-[r:ENFORCES|REGULATES]->(reg:Entity)
WHERE n.name CONTAINS "Environment Agency" OR n.name = "NEA"
RETURN n.name, type(r) AS relationship, reg.name, reg.type, r.evidence LIMIT 25

Q: Which organisations collaborate with NEA?
MATCH (n:Entity {name: "National Environment Agency"})-[r:COLLABORATES_WITH]-(org:Entity)
RETURN org.name, org.type, r.evidence LIMIT 20

Q: What environmental indicators are measured?
MATCH (n:Entity)-[r:MEASURES]->(m:Entity)
RETURN n.name, m.name AS indicator, m.type, r.evidence, r.confidence LIMIT 25

Q: Which facilities are in Singapore?
MATCH (f:Entity)-[r:LOCATED_IN]->(g:Entity)
WHERE g.name CONTAINS "Singapore"
RETURN f.name, f.type, g.name, r.evidence LIMIT 25

Q: What targets has NEA set?
MATCH (n:Entity)-[r:SET_TARGET|TARGETS]->(t:Entity)
WHERE n.name CONTAINS "Environment Agency" OR n.name = "NEA"
RETURN n.name, type(r), t.name, t.type, r.evidence, r.confidence LIMIT 25

Q: What pollutants are emitted and by whom?
MATCH (src:Entity)-[r:EMITS]->(p:Entity)
RETURN src.name, src.type, p.name AS pollutant, r.evidence LIMIT 25

Q: What technologies does NEA use or operate?
MATCH (n:Entity)-[r]-(t:Entity:Technology)
WHERE n.name CONTAINS "Environment Agency" OR n.name = "NEA"
RETURN t.name, type(r), n.name, r.evidence LIMIT 20

Q: Show me the most connected entities
MATCH (n:Entity)
WITH n, size([(n)-[]-() | 1]) AS degree
RETURN n.name, n.type, degree ORDER BY degree DESC LIMIT 20
"""


# ---------------------------------------------------------------------------
# Safety: block write operations
# ---------------------------------------------------------------------------

_WRITE_PATTERN = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|CALL\s+apoc\.refactor)\b",
    re.IGNORECASE,
)


def _is_safe(cypher: str) -> bool:
    return not bool(_WRITE_PATTERN.search(cypher))


# ---------------------------------------------------------------------------
# Extract Cypher from LLM response
# ---------------------------------------------------------------------------

def _extract_cypher(raw: str) -> str:
    # Strip /no_think / <think> blocks
    if "<think>" in raw:
        end = raw.find("</think>")
        raw = raw[end + 8:].strip() if end != -1 else raw.split("<think>")[0].strip()

    # Extract from markdown code block
    code_block = re.search(r"```(?:cypher)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()

    # Find first MATCH statement
    match_pos = raw.upper().find("MATCH")
    if match_pos != -1:
        return raw[match_pos:].strip()

    return raw.strip()


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class NLToCypherEngine:
    def __init__(self, graph_client: Neo4jClient, ollama_base_url: str) -> None:
        self.graph_client = graph_client
        self.ollama = OllamaClient(ollama_base_url, CHAT_MODEL, timeout_seconds=180)

    def _build_cypher_prompt(
        self,
        question: str,
        history: list[dict[str, Any]],
    ) -> str:
        context_block = ""
        if history:
            lines = []
            for turn in history[-3:]:  # last 3 turns
                lines.append(f"User: {turn['question']}")
                if turn.get("cypher"):
                    lines.append(f"Cypher used: {turn['cypher']}")
                lines.append(f"Answer summary: {turn['answer'][:200]}")
            context_block = "\nCONVERSATION CONTEXT (last turns)\n" + "\n".join(lines) + "\n"

        return f"""/no_think
You are a Neo4j Cypher expert. Generate a single read-only Cypher MATCH query for the question below.

{_SCHEMA_BLOCK}

{_FEW_SHOT}
{context_block}
RULES:
- Output ONLY the Cypher query, no explanation, no markdown fences
- Use only MATCH, WHERE, RETURN, WITH, ORDER BY, LIMIT — never MERGE, CREATE, SET, DELETE
- Always LIMIT results to at most 50
- Use CONTAINS for partial name matches (entity names may be long)
- Return the evidence and confidence properties when available
- If the question is a follow-up, use the conversation context above

QUESTION: {question}

CYPHER:"""

    def _build_answer_prompt(
        self,
        question: str,
        cypher: str,
        results: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> str:
        context_block = ""
        if history:
            prev = history[-1]
            context_block = f"\nPrevious question: {prev['question']}\nPrevious answer: {prev['answer'][:300]}\n"

        results_str = ""
        if results:
            for i, row in enumerate(results[:30], 1):
                results_str += f"{i}. {row}\n"
        else:
            results_str = "(no results returned)"

        return f"""/no_think
Answer the question using ONLY the graph query results below. Be concise and factual.
If results are empty, say "No data found in the knowledge graph for this question."
Do not invent information not present in the results.
Cite evidence strings when available.
{context_block}
Question: {question}

Cypher executed:
{cypher}

Results ({len(results)} rows):
{results_str}

Answer:"""

    def ask(
        self,
        question: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Pass 1: generate Cypher
        cypher_prompt = self._build_cypher_prompt(question, history)
        raw_cypher = self.ollama.generate(cypher_prompt, temperature=0.0)
        cypher = _extract_cypher(raw_cypher)

        # Safety check
        if not _is_safe(cypher):
            return {
                "question": question,
                "cypher": cypher,
                "results": [],
                "answer": "I generated an unsafe query (write operation). Please rephrase.",
                "error": "unsafe_cypher",
            }

        # Execute Cypher
        results: list[dict[str, Any]] = []
        error: str | None = None
        try:
            results = self.graph_client.run_query(cypher)
        except Exception as exc:
            error = str(exc)

        if error:
            # Try a fallback simple query
            fallback = (
                "MATCH (n:Entity) "
                f"WHERE n.name CONTAINS $term "
                "RETURN n.name, n.type, n.aliases LIMIT 20"
            )
            # Extract likely entity name from question (first capitalised token)
            tokens = [w for w in question.split() if w and w[0].isupper()]
            term = tokens[0] if tokens else question[:30]
            try:
                results = self.graph_client.run_query(fallback, {"term": term})
                cypher = fallback + f"  -- (fallback, original failed: {error[:80]})"
                error = None
            except Exception:
                pass

        # Pass 2: synthesise answer
        answer_prompt = self._build_answer_prompt(question, cypher, results, history)
        answer = self.ollama.generate(answer_prompt, temperature=0.1).strip()

        # Strip any leaked think tags from answer
        if "<think>" in answer:
            end = answer.find("</think>")
            answer = answer[end + 8:].strip() if end != -1 else answer.split("<think>")[0].strip()

        if not answer:
            answer = "No results found in the knowledge graph for this question."

        return {
            "question": question,
            "cypher": cypher,
            "results": results,
            "answer": answer,
            "error": error,
        }
