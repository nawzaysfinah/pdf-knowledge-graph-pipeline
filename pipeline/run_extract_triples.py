"""CLI runner for Stage 5: LLM Triple Extraction.

Usage:
    python -m pipeline.run_extract_triples
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from pipeline.ontology import load_ontology, print_summary
from pipeline.triple_extractor import (
    CHUNKS_PATH,
    EXTRACTIONS_PATH,
    ONTOLOGY_PATH,
    extract_all,
)
from src.llm.ollama_client import OllamaClient

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    ollama_url   = os.environ["OLLAMA_URL"]
    ollama_model = os.environ["OLLAMA_MODEL"]

    client = OllamaClient(base_url=ollama_url, model=ollama_model, timeout_seconds=180)

    print(f"\n  Ollama URL   : {ollama_url}")
    print(f"  Model        : {ollama_model}")

    if not client.health():
        print("  ERROR: Ollama is not reachable. Is it running?")
        raise SystemExit(1)
    print("  Ollama       : reachable\n")

    ontology = load_ontology(ONTOLOGY_PATH)
    print_summary(ontology)

    if not CHUNKS_PATH.exists():
        print(f"  ERROR: {CHUNKS_PATH} not found. Run Stage 3 first.")
        raise SystemExit(1)

    print(f"  Input        : {CHUNKS_PATH}")
    print(f"  Output       : {EXTRACTIONS_PATH}")
    print(f"\n  Starting extraction...\n")

    stats = extract_all(CHUNKS_PATH, EXTRACTIONS_PATH, client, ontology)

    print(f"\n── Extraction Complete ──────────────────────────────")
    print(f"  Chunks processed : {stats['chunks_processed']}")
    print(f"  Entities found   : {stats['entities_found']}")
    print(f"  Triples found    : {stats['triples_found']}")
    print(f"  Errors           : {stats['errors']}")
    print(f"\n  Output: {EXTRACTIONS_PATH.resolve()}")


if __name__ == "__main__":
    main()
