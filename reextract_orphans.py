"""Re-extract triples for orphan chunks using Claude claude-haiku-4-5.

Uses a relaxed confidence threshold (0.5) and entity-seeded prompts
to connect the 877 orphan nodes that have no relationships.

Reads:   output/orphan_chunks.jsonl
         output/ontology.json
Writes:  output/reextracted_triples.jsonl   (flat triples, ready for ingest)

Usage:
    python reextract_orphans.py
    python reextract_orphans.py --dry-run   # show 3 sample prompts, no API calls
    python reextract_orphans.py --limit 50  # process first N chunks only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:0.6b")

ORPHAN_CHUNKS_PATH   = Path("output/orphan_chunks.jsonl")
ONTOLOGY_PATH        = Path("output/ontology.json")
OUTPUT_PATH          = Path("output/reextracted_triples.jsonl")

CONFIDENCE_THRESHOLD = 0.6
INTER_CALL_SLEEP     = 0.3


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def load_ontology(path: Path) -> tuple[list[str], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    types      = [e["type"] for e in data["entity_types"]]
    predicates = [r["predicate"] for r in data["relationship_types"]]
    return types, predicates


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(
    chunk_text: str,
    orphan_entities: list[str],
    valid_types: list[str],
    valid_predicates: list[str],
) -> str:
    entity_list = ", ".join(f'"{e}"' for e in orphan_entities[:15])
    types_str   = ", ".join(valid_types)
    preds_str   = ", ".join(valid_predicates)

    return f"""/no_think
You are extracting relationships from a document chunk.
Focus specifically on finding relationships that connect these known entities to other entities in the text:

KNOWN ENTITIES TO CONNECT: {entity_list}

Your task:
1. Find any relationship in the text that involves one of the KNOWN ENTITIES above as subject OR object
2. Also extract any other valid triples you find

RULES:
- predicate MUST be from this list exactly: {preds_str}
- entity type MUST be from this list exactly: {types_str}
- entity name: proper noun or noun phrase, max 60 chars, max 8 words, starts with capital letter
- confidence: use 0.6 as minimum threshold (relaxed from pipeline default)
- if a relationship is implied but reasonably certain, set confidence 0.6-0.69
- if explicitly stated, set confidence 0.7-1.0

Return ONLY valid JSON, no explanation:
{{"entities":[{{"name":"...","type":"..."}}],"triples":[{{"subject":"...","subject_type":"...","predicate":"...","object":"...","object_type":"...","evidence":"...","confidence":0.0}}]}}

TEXT:
{chunk_text}"""


# ---------------------------------------------------------------------------
# Ollama call
# ---------------------------------------------------------------------------

def call_ollama(prompt: str) -> dict:
    for attempt in range(1, 3):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=90,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")

            # Strip leaked <think>...</think>
            if "<think>" in raw:
                end = raw.find("</think>")
                raw = raw[end + 8:].strip() if end != -1 else raw.split("<think>")[0].strip()

            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start == -1 or end == 0:
                logger.warning("No JSON in response (attempt %d)", attempt)
                continue
            return json.loads(raw[start:end])

        except (requests.exceptions.ReadTimeout, requests.exceptions.HTTPError) as e:
            logger.warning("Ollama error attempt %d: %s", attempt, e)
            time.sleep(3)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse error attempt %d: %s", attempt, e)
            time.sleep(1)

    return {"entities": [], "triples": []}


# ---------------------------------------------------------------------------
# Validation — enforce ontology, filter < 0.5 confidence
# ---------------------------------------------------------------------------

def validate_and_flatten(
    result: dict,
    chunk: dict,
    valid_types: set[str],
    valid_predicates: set[str],
) -> list[dict]:
    flat = []
    for t in result.get("triples", []):
        pred = str(t.get("predicate", "")).strip()
        conf = float(t.get("confidence", 0.0))
        subj = str(t.get("subject", "")).strip()
        obj  = str(t.get("object",  "")).strip()

        if conf < CONFIDENCE_THRESHOLD:
            continue
        if pred not in valid_predicates:
            continue
        if len(subj) < 4 or len(obj) < 4:
            continue
        if not subj[0].isupper() or not obj[0].isupper():
            continue
        s_type = t.get("subject_type", "")
        o_type = t.get("object_type",  "")
        if s_type not in valid_types or o_type not in valid_types:
            continue

        flat.append({
            "subject":       subj,
            "subject_type":  s_type,
            "predicate":     pred,
            "object":        obj,
            "object_type":   o_type,
            "evidence":      t.get("evidence", ""),
            "confidence":    conf,
            "chunk_id":      chunk.get("chunk_id", ""),
            "doc_id":        chunk.get("doc_id", ""),
            "filename":      chunk.get("filename", ""),
            "page_num":      chunk.get("page_num", 0),
            "ontology_valid": True,
            "violation":     None,
            "subject_canonical_id": None,
            "object_canonical_id":  None,
            "source":        "reextraction_pass",
        })
    return flat


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print 3 sample prompts without calling API")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only first N chunks (0 = all)")
    args = parser.parse_args()

    valid_types, valid_predicates = load_ontology(ONTOLOGY_PATH)
    valid_types_set      = set(valid_types)
    valid_predicates_set = set(valid_predicates)

    chunks = []
    with ORPHAN_CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                if len(c.get("text", "")) > 50:  # skip empty/stub chunks
                    chunks.append(c)

    if args.limit:
        chunks = chunks[:args.limit]

    logger.info("Processing %d orphan chunks (with usable text)", len(chunks))

    # Resume support
    done_ids: set[str] = set()
    if OUTPUT_PATH.exists():
        with OUTPUT_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line).get("chunk_id", ""))
        if done_ids:
            logger.info("Resuming — %d chunk IDs already written", len(done_ids))

    pred_counter: Counter = Counter()
    orphan_connected: set[str] = set()
    total_new = 0
    dry_count = 0

    with OUTPUT_PATH.open("a", encoding="utf-8") as out:
        for i, chunk in enumerate(chunks):
            chunk_id = chunk.get("chunk_id", "")
            if chunk_id in done_ids:
                continue

            prompt = build_prompt(
                chunk_text       = chunk["text"],
                orphan_entities  = chunk.get("orphan_entities", []),
                valid_types      = valid_types,
                valid_predicates = valid_predicates,
            )

            if args.dry_run:
                print(f"\n{'='*60}")
                print(f"Chunk {i+1}: {chunk_id}  ({chunk['filename']} p.{chunk['page_num']})")
                print(f"Orphans: {chunk['orphan_entities']}")
                print(f"Prompt:\n{prompt[:700]}...")
                dry_count += 1
                if dry_count >= 3:
                    print("\n[dry-run] Stopping after 3 examples.")
                    break
                continue

            result = call_ollama(prompt)
            flat   = validate_and_flatten(result, chunk, valid_types_set, valid_predicates_set)

            # Track which orphans got connected
            for t in flat:
                for name in chunk.get("orphan_entities", []):
                    if t["subject"] == name or t["object"] == name:
                        orphan_connected.add(name)
                pred_counter[t["predicate"]] += 1

            # Write all triples (one per line) tagged with chunk_id for dedup
            for t in flat:
                out.write(json.dumps(t, ensure_ascii=False) + "\n")

            total_new += len(flat)

            logger.info(
                "[%d/%d] %s p.%s  orphans=%d  new_triples=%d",
                i + 1, len(chunks),
                chunk.get("filename", "?"),
                chunk.get("page_num", "?"),
                len(chunk.get("orphan_entities", [])),
                len(flat),
            )
            time.sleep(INTER_CALL_SLEEP)

    if not args.dry_run:
        print(f"\n{'='*60}")
        print(f"  Total chunks processed       : {len(chunks) - len(done_ids)}")
        print(f"  Total new triples found      : {total_new}")
        print(f"  Orphan entities now connected: {len(orphan_connected)}")
        print(f"\n  New triples by predicate:")
        for pred, count in pred_counter.most_common(15):
            print(f"    {count:>5}  {pred}")
        print(f"\n  Output → {OUTPUT_PATH}")
        print(f"\nNext step: python ingest_reextracted.py")


if __name__ == "__main__":
    main()
