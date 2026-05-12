"""Triple extraction pipeline using local Ollama model output."""

from __future__ import annotations

import json
import re
from typing import Any

from src.llm.ollama_client import OllamaClient


ENTITY_KEYS = ["initiatives", "topics", "issues", "learnings", "outcomes"]


def extraction_prompt(doc_id: str, text: str) -> str:
    """Prompt for entity and relation extraction into strict JSON."""
    return f"""
You are extracting structured knowledge graph triples.
Output only valid JSON. No markdown. No explanations.
Use this schema exactly:
{{
  "doc_id": "{doc_id}",
  "entities": {{
    "initiatives": [{{"name": "", "description": ""}}],
    "topics": [{{"name": ""}}],
    "issues": [{{"name": ""}}],
    "learnings": [{{"text": ""}}],
    "outcomes": [{{"name": ""}}]
  }},
  "relations": [
    {{"source_type":"Document","source_id":"{doc_id}","rel":"ABOUT","target_type":"Initiative","target_key":"name","target_value":""}},
    {{"source_type":"Document","source_id":"{doc_id}","rel":"MENTIONS","target_type":"Topic","target_key":"name","target_value":""}},
    {{"source_type":"Document","source_id":"{doc_id}","rel":"CAPTURES","target_type":"Learning","target_key":"text","target_value":""}},
    {{"source_type":"Learning","source_id":"<learning_text>","source_value":"<learning_text>","rel":"RELATES_TO","target_type":"Topic","target_key":"name","target_value":""}},
    {{"source_type":"Learning","source_id":"<learning_text>","source_value":"<learning_text>","rel":"ADDRESSES","target_type":"Issue","target_key":"name","target_value":""}},
    {{"source_type":"Initiative","source_id":"<initiative_name>","source_value":"<initiative_name>","rel":"ADDRESSES","target_type":"Issue","target_key":"name","target_value":""}},
    {{"source_type":"Initiative","source_id":"<initiative_name>","source_value":"<initiative_name>","rel":"RESULTED_IN","target_type":"Outcome","target_key":"name","target_value":""}}
  ],
  "confidence": {{}}
}}
Rules:
- Use only facts grounded in the provided text.
- Avoid duplicates.
- If unknown, return empty arrays.
Text:
{text}
""".strip()


def _extract_first_json_block(text: str) -> str:
    """Extract the first balanced JSON object from arbitrary model output."""
    candidate = text.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output")

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError("Unbalanced JSON object in model output")


def parse_json_response(raw_output: str, doc_id: str) -> dict[str, Any]:
    """Parse and normalize extraction JSON payload."""
    parsed = json.loads(_extract_first_json_block(raw_output))

    payload = {
        "doc_id": str(parsed.get("doc_id") or doc_id),
        "entities": parsed.get("entities") or {},
        "relations": parsed.get("relations") or [],
        "confidence": parsed.get("confidence") or {},
    }

    entities = payload["entities"]
    if not isinstance(entities, dict):
        entities = {}

    normalized_entities: dict[str, list[dict[str, str]]] = {}
    for key in ENTITY_KEYS:
        values = entities.get(key, [])
        if not isinstance(values, list):
            values = []
        cleaned = []
        for item in values:
            if not isinstance(item, dict):
                continue
            if key == "learnings":
                text = str(item.get("text", "")).strip()
                if text:
                    cleaned.append({"text": text})
            elif key == "initiatives":
                name = str(item.get("name", "")).strip()
                if name:
                    cleaned.append(
                        {
                            "name": name,
                            "description": str(item.get("description", "")).strip(),
                        }
                    )
            else:
                name = str(item.get("name", "")).strip()
                if name:
                    cleaned.append({"name": name})
        normalized_entities[key] = cleaned

    relations = payload.get("relations", [])
    if not isinstance(relations, list):
        relations = []

    normalized_relations = []
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        item = {
            "source_type": str(relation.get("source_type", "")).strip(),
            "source_id": str(relation.get("source_id", doc_id)).strip() or doc_id,
            "source_value": str(relation.get("source_value", "")).strip(),
            "rel": str(relation.get("rel", "")).strip(),
            "target_type": str(relation.get("target_type", "")).strip(),
            "target_key": str(relation.get("target_key", "")).strip(),
            "target_value": str(relation.get("target_value", "")).strip(),
        }
        if item["rel"] and item["target_value"] and item["target_type"]:
            normalized_relations.append(item)

    payload["entities"] = normalized_entities
    payload["relations"] = normalized_relations
    return payload


def extract_triples_for_document(
    ollama_client: OllamaClient,
    doc_id: str,
    text: str,
) -> dict[str, Any]:
    """Extract triples with one retry if JSON parsing fails."""
    prompt = extraction_prompt(doc_id=doc_id, text=text)

    raw = ollama_client.generate(prompt, json_mode=False, temperature=0.0)
    try:
        return parse_json_response(raw, doc_id=doc_id)
    except (json.JSONDecodeError, ValueError):
        retry_prompt = (
            prompt
            + "\n\nIMPORTANT: Return strict JSON only. No prose, no markdown, no comments."
        )
        retry_raw = ollama_client.generate(retry_prompt, json_mode=True, temperature=0.0)
        return parse_json_response(retry_raw, doc_id=doc_id)
