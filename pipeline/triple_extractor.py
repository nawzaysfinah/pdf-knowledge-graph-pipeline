"""Stage 5: LLM Triple Extraction Module.

For each chunk in output/chunks.jsonl, calls the local Ollama model and
extracts entities + triples grounded in the domain ontology.

Output schema per extraction:
  {chunk_id, doc_id, filename, page_num, section_heading,
   entities: [{name, type, aliases}],
   triples:  [{subject, subject_type, predicate, object, object_type,
               evidence, confidence, chunk_id, doc_id, page_num, filename}]}

Saves to: output/extractions.jsonl
Re-run safe: already-processed chunk_ids are skipped.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from src.llm.ollama_client import OllamaClient
from pipeline.ontology import Ontology, load_ontology

logger = logging.getLogger(__name__)

CHUNKS_PATH      = Path("output") / "chunks.jsonl"
EXTRACTIONS_PATH = Path("output") / "extractions.jsonl"
ONTOLOGY_PATH    = Path("output") / "ontology.json"

MAX_RETRIES    = 3
RETRY_BASE_SEC = 2


# ---------------------------------------------------------------------------
# Prompt builder — generated from the live ontology
# ---------------------------------------------------------------------------

def _build_prompt(ontology: Ontology, chunk_text: str) -> str:
    entity_lines = "\n".join(
        f"  - {e.type}: {e.description} (e.g. {', '.join(e.examples[:2])})"
        for e in ontology.entity_types
    )

    rel_lines = "\n".join(
        f"  - {r.predicate}: [{' | '.join(r.allowed_subject_types)}]"
        f" → [{' | '.join(r.allowed_object_types)}]"
        for r in ontology.relationship_types
    )

    return f"""You are a knowledge graph extraction expert for a government environmental agency.
Extract entities and relationships from the text. Return ONLY valid JSON — no markdown, no explanation.

ENTITY TYPES (use exactly these type names):
{entity_lines}

RELATIONSHIP PREDICATES (subject → predicate → object):
{rel_lines}

OUTPUT FORMAT:
{{
  "entities": [
    {{"name": "<name>", "type": "<type from list above>", "aliases": ["<alt name>"]}}
  ],
  "triples": [
    {{
      "subject": "<entity name>",
      "subject_type": "<entity type>",
      "predicate": "<predicate from list above>",
      "object": "<entity name>",
      "object_type": "<entity type>",
      "evidence": "<verbatim quote from text, max 20 words>",
      "confidence": <float 0.0–1.0>
    }}
  ]
}}

RULES:
- Extract only facts explicitly stated or strongly implied in the text.
- Use only entity types and predicates from the lists above.
- Evidence must be a verbatim phrase from the text (≤ 20 words).
- Confidence: 1.0 = explicitly stated, 0.7–0.9 = strongly implied. Do not include below 0.7.
- Every triple entity must also appear in the entities list.
- If nothing relevant found, return: {{"entities": [], "triples": []}}

TEXT:
{chunk_text}"""


# ---------------------------------------------------------------------------
# JSON extraction from raw model output
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict[str, Any]:
    """Pull the first balanced JSON object from model output and parse it."""
    text = raw.strip()

    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))

    # Already bare JSON
    if text.startswith("{"):
        return json.loads(text)

    # Find first { and walk to matching }
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("Unbalanced JSON in model output")


def _normalise_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Ensure result has the expected keys and list types."""
    return {
        "entities": raw.get("entities") if isinstance(raw.get("entities"), list) else [],
        "triples":  raw.get("triples")  if isinstance(raw.get("triples"),  list) else [],
    }


# ---------------------------------------------------------------------------
# Single-chunk extraction with retry
# ---------------------------------------------------------------------------

def extract_chunk(
    chunk: dict[str, Any],
    client: OllamaClient,
    ontology: Ontology,
) -> dict[str, Any]:
    """Call the LLM for one chunk. Retries up to MAX_RETRIES on bad JSON."""
    prompt = _build_prompt(ontology, chunk["text"])
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = client.generate(prompt, json_mode=True, temperature=0.0)
            parsed = _normalise_result(_extract_json(raw))

            # Attach chunk provenance to every triple
            for triple in parsed["triples"]:
                triple.update({
                    "chunk_id":        chunk["chunk_id"],
                    "doc_id":          chunk["doc_id"],
                    "filename":        chunk["filename"],
                    "page_num":        chunk["page_num"],
                    "section_heading": chunk.get("section_heading", ""),
                })

            return {
                "chunk_id":        chunk["chunk_id"],
                "doc_id":          chunk["doc_id"],
                "filename":        chunk["filename"],
                "page_num":        chunk["page_num"],
                "section_heading": chunk.get("section_heading", ""),
                "entities":        parsed["entities"],
                "triples":         parsed["triples"],
            }

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_error = exc
            wait = RETRY_BASE_SEC ** attempt
            logger.warning(
                "chunk %s — attempt %d/%d failed (%s), retrying in %ds",
                chunk["chunk_id"], attempt, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)

    logger.error(
        "chunk %s — all %d attempts failed (%s). Saving empty result.",
        chunk["chunk_id"], MAX_RETRIES, last_error,
    )
    return {
        "chunk_id":        chunk["chunk_id"],
        "doc_id":          chunk["doc_id"],
        "filename":        chunk["filename"],
        "page_num":        chunk["page_num"],
        "section_heading": chunk.get("section_heading", ""),
        "entities":        [],
        "triples":         [],
        "error":           str(last_error),
    }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def extract_all(
    chunks_path: Path,
    output_path: Path,
    client: OllamaClient,
    ontology: Ontology,
) -> dict[str, int]:
    """Process all chunks, skip already-extracted ones.

    Returns running stats dict.
    """
    chunks_path = Path(chunks_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load already-processed chunk_ids
    processed: set[str] = set()
    if output_path.exists():
        with output_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        processed.add(json.loads(line)["chunk_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass

    # Load all chunks
    chunks: list[dict[str, Any]] = []
    with chunks_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))

    pending = [c for c in chunks if c["chunk_id"] not in processed]
    logger.info(
        "Chunks total=%d  already_done=%d  to_process=%d",
        len(chunks), len(processed), len(pending),
    )

    stats = {"chunks_processed": 0, "entities_found": 0, "triples_found": 0, "errors": 0}

    with output_path.open("a", encoding="utf-8") as out:
        for chunk in pending:
            result = extract_chunk(chunk, client, ontology)
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()

            stats["chunks_processed"] += 1
            stats["entities_found"]   += len(result["entities"])
            stats["triples_found"]    += len(result["triples"])
            if "error" in result:
                stats["errors"] += 1

            # Running stats line
            print(
                f"\r  processed={stats['chunks_processed']}/{len(pending)}"
                f"  entities={stats['entities_found']}"
                f"  triples={stats['triples_found']}"
                f"  errors={stats['errors']}",
                end="", flush=True,
            )

    print()  # newline after progress line
    return stats
