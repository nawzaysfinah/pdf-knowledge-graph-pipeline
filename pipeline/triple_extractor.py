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

from requests.exceptions import ReadTimeout

from src.llm.ollama_client import OllamaClient
from pipeline.ontology import Ontology, load_ontology

logger = logging.getLogger(__name__)

CHUNKS_PATH        = Path("output") / "chunks.jsonl"
EXTRACTIONS_PATH   = Path("output") / "extractions.jsonl"
ONTOLOGY_PATH      = Path("output") / "ontology.json"
CANONICAL_MAP_PATH = Path("output") / "canonical_map.json"

MAX_RETRIES    = 3
RETRY_BASE_SEC = 2


# ---------------------------------------------------------------------------
# Known-entity seeder — Fix B
# ---------------------------------------------------------------------------

def _load_known_entities(canonical_map_path: Path) -> str:
    """Build a compact hint list of known canonical entities for the prompt."""
    if not canonical_map_path.exists():
        return ""
    canonical_map = json.loads(canonical_map_path.read_text())
    # Deduplicate by canonical_id, group by type
    seen: dict[str, str] = {}  # canonical_id → "Name (Type)"
    for entry in canonical_map.values():
        cid = entry["canonical_id"]
        if cid not in seen:
            seen[cid] = f"{entry['canonical_name']} ({entry['type']})"
    if not seen:
        return ""
    lines = "\n".join(f"  - {v}" for v in sorted(seen.values()))
    return f"\nKNOWN ENTITIES (already in the graph — use these exact names if they appear):\n{lines}\n"


# ---------------------------------------------------------------------------
# Prompt builder — Fix B + C: pre-seeding + aggressive extraction
# ---------------------------------------------------------------------------

def _build_prompt(ontology: Ontology, chunk_text: str, known_entities: str = "") -> str:
    # Compact entity list: just type names, no descriptions
    entity_types = " | ".join(e.type for e in ontology.entity_types)

    # Compact predicate list: predicate only
    predicates = " | ".join(r.predicate for r in ontology.relationship_types)

    return f"""/no_think
Extract entities and relationships from the text. Return ONLY JSON, no explanation.

ENTITY TYPES: {entity_types}
PREDICATES: {predicates}
{known_entities}
OUTPUT:
{{"entities":[{{"name":"...","type":"...","aliases":[]}}],"triples":[{{"subject":"...","subject_type":"...","predicate":"...","object":"...","object_type":"...","evidence":"...","confidence":0.0}}]}}

RULES: Extract every entity and relationship, including implied ones. Confidence: 1.0=explicit, 0.7=implied. Every triple entity must be in entities list.

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
    known_entities: str = "",
) -> dict[str, Any]:
    """Call the LLM for one chunk. Retries up to MAX_RETRIES on bad JSON."""
    prompt = _build_prompt(ontology, chunk["text"], known_entities)
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

        except (json.JSONDecodeError, ValueError, KeyError, ReadTimeout) as exc:
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
    canonical_map_path: Path = CANONICAL_MAP_PATH,
) -> dict[str, int]:
    """Process all chunks, skip already-extracted ones.

    Loads known entities from canonical_map_path (if present) and injects
    them into every prompt so the model recognises previously seen entities.

    Returns running stats dict.
    """
    chunks_path = Path(chunks_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Fix B: build known-entity hint string once, reuse for every chunk
    known_entities = _load_known_entities(canonical_map_path)
    if known_entities:
        logger.info("Loaded known-entity hints from %s", canonical_map_path)

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
            result = extract_chunk(chunk, client, ontology, known_entities)
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
