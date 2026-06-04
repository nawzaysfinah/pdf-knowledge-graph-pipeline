# PDF → Knowledge Graph Pipeline

> Extract structured, queryable knowledge from unstructured PDF documents using a local LLM — no cloud APIs, no data leaving your machine.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Neo4j](https://img.shields.io/badge/Neo4j-5.20-008CC1?logo=neo4j&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-local_LLM-black)
![License](https://img.shields.io/badge/license-MIT-green)

---

## The Problem

Government agencies, law firms, research teams — anyone dealing with large document corpora — face the same problem: **the knowledge is in the PDFs, but it's not queryable**.

You can keyword-search. You can ask an LLM to summarise. But you can't ask *"which regulations does this facility comply with, and which organisation enforces them?"* without someone manually building that map.

This pipeline automates that map-building. Drop in PDFs; get back a graph database of entities and relationships you can query with Cypher, visualise in Neo4j Browser, or feed into a RAG system.

---

## What It Does

```
PDFs → Extract Text → Chunk → LLM Triple Extraction → Entity Resolution → Validate → Neo4j
```

Given a folder of PDF documents, the pipeline:

1. **Extracts text** — handles both digital and scanned (OCR) PDFs
2. **Chunks intelligently** — heading-aware boundaries, tables kept atomic, short chunks merged for LLM context
3. **Extracts triples** — a local LLM identifies entities (e.g. `National Environment Agency`) and relationships (e.g. `regulates → air emissions`) as `(subject, predicate, object)` triples with evidence quotes
4. **Resolves entities** — sentence-transformer embeddings + cosine similarity merge aliases (`NEA` = `National Environment Agency`)
5. **Validates against an ontology** — 18 entity types and 20 predicates enforced; violations flagged but kept for review
6. **Ingests idempotently** — MERGE operations mean you can safely re-run without duplicating data

The result is a knowledge graph you can query:

```cypher
// Who is most connected in the document corpus?
MATCH (n:Entity)
WITH n, size([(n)-[]-() | 1]) AS degree
RETURN n.name, n.type, degree ORDER BY degree DESC LIMIT 20

// Trace a regulatory chain with evidence
MATCH (a:Entity)-[r]->(b:Entity)
RETURN a.name, type(r), b.name, r.evidence, r.confidence
ORDER BY r.confidence DESC
```

---

## Architecture

```
PDFs (pdfs/)
     │
     ▼
Stage 2 · PDF Extraction        pymupdf4llm (text) / pytesseract (scanned)
     │                          pdfplumber (tables)
     ▼
output/extractions/<doc_id>.json
     │
     ▼
Stage 3 · Chunking              heading → paragraph boundaries, 1-2 sentence overlap
     │                          short chunks (<300 chars) merged for LLM context
     │                          tables kept atomic
     ▼
output/chunks.jsonl
     │
     ▼
Stage 5 · LLM Triple Extraction Ollama (qwen3:0.6b recommended) + compact ontology prompt
     │                          /no_think directive for faster qwen3 inference
     │                          entity pre-seeding from canonical_map
     │
     ▼
output/extractions.jsonl
     │
     ▼
Stage 6 · Entity Resolution     sentence-transformers all-MiniLM-L6-v2
     │                          alias-based merge + cosine similarity (≥0.92)
     │                          interactive confirmation
     ▼
output/canonical_map.json
     │
     ▼
Stage 7 · Validation            confidence filter (< 0.5 dropped)
     │                          ontology type-constraint check (violations flagged, kept)
     ▼
output/validated_triples.jsonl
     │
     ▼
Stage 8 · Neo4j Ingestion       MERGE nodes + relationships (idempotent)
     │                          dual labels (:Entity:<Type>), label sanitization
     ▼
Neo4j  bolt://localhost:7687
```

---

## Key Engineering Decisions

**Why a local LLM (Ollama) instead of the OpenAI/Claude API?**
The target use case involves sensitive government documents. Keeping inference local means no data leaves the machine. `qwen3:0.6b` (500 MB) runs on CPU at reasonable speed; quality scales up if you have a GPU.

**Why Neo4j instead of a vector database?**
Vector databases are great for semantic similarity ("find me similar chunks"). Graph databases are great for relationship traversal ("trace the chain from a pollutant to the regulation that controls it"). This pipeline is optimised for the latter — multi-hop queries that would require many RAG round-trips become single Cypher queries.

**Why a fixed ontology (18 types, 20 predicates) instead of open extraction?**
Open extraction produces inconsistent predicates (`employs`, `has_employee`, `hired`) that can't be reliably queried. A compact ontology forces the LLM to normalise, at the cost of some recall. The validation stage flags violations rather than dropping them, so you can extend the ontology when you find legitimate gaps.

**Why idempotent ingestion (MERGE)?**
Large document sets can take hours to process. The pipeline checkpoints after every stage so you can kill it, fix a config, and resume without reprocessing. This also means you can incrementally add documents to an existing graph.

---

## Challenges Solved

| Problem | Solution |
|---|---|
| LLM inventing entity types outside the ontology | Prompt constraint + `validate_extractions.py` type filter |
| Entity aliases (`NEA` ≠ `National Environment Agency`) bloating the graph | Sentence-transformer cosine similarity merge at Stage 6 |
| Scanned PDFs with no digital text layer | Tesseract OCR fallback via `pytesseract` + `pdf2image` |
| Long overnight runs crashing due to Ollama OOM | `run_overnight.sh` watchdog — auto-restarts Ollama, resumes from last checkpoint |
| Neo4j labels crashing on special characters in entity names | `_safe_label()` sanitization before ingestion |

---

## Tech Stack

| Layer | Technology |
|---|---|
| PDF extraction | `pymupdf4llm`, `pdfplumber`, `pytesseract` |
| LLM inference | Ollama (`qwen3:0.6b` recommended) |
| Entity resolution | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Graph database | Neo4j 5.20 + APOC (Docker) |
| Graph queries | Cypher |
| Orchestration | Python 3.10+, Shell |

---

## Quickstart

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Docker Desktop | for Neo4j |
| Ollama | must be running locally (`ollama serve`) |
| `qwen3:0.6b` model | `ollama pull qwen3:0.6b` — fastest on CPU |
| Tesseract *(optional)* | `brew install tesseract` — only for scanned PDFs |

### Setup

```bash
# 1. Clone and create virtual environment
git clone https://github.com/nawzaysfinah/pdf-knowledge-graph-pipeline.git
cd pdf-knowledge-graph-pipeline
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements-pipeline.txt

# 3. Configure environment
cp .env.example .env          # defaults work out of the box

# 4. Start Neo4j
docker compose up -d           # available at http://localhost:7474

# 5. Validate environment
python -m pipeline.validate_env
```

### Run the pipeline

```bash
# Drop your PDFs in
cp /path/to/your/documents/*.pdf pdfs/

# Run all stages
python -m pipeline.run_extract          # Stage 2 — extract text + tables
python -m pipeline.run_chunk            # Stage 3 — chunk into semantic units
python -m pipeline.run_extract_triples  # Stage 5 — LLM triple extraction
echo "y" | python -m pipeline.run_resolve  # Stage 6 — entity resolution
python -m pipeline.run_validate         # Stage 7 — validate + filter
python -m pipeline.run_ingest           # Stage 8 — write to Neo4j
python -m pipeline.run_smoke_tests      # Stage 9 — verify graph

# For large collections (overnight run with auto-resume)
bash run_overnight.sh
```

### Re-run behaviour

Each stage checkpoints its output — re-running skips already-processed items:

| Stage | On re-run |
|---|---|
| Extract | Skips PDFs with unchanged checksum |
| Chunk | Skips doc_ids already in `chunks.jsonl` |
| LLM Triples | Skips chunk_ids already in `extractions.jsonl` |
| Ingest | Always safe — `MERGE` is idempotent |

---

## Domain Ontology

The default ontology targets environmental/regulatory documents (NEA Singapore context) but is fully customisable at `output/ontology.json`.

**18 entity types:** `GovernmentAgency` · `Regulation` · `Policy` · `Programme` · `Pollutant` · `WasteType` · `Facility` · `Organisation` · `Person` · `EnvironmentalIndicator` · `ClimateEvent` · `GeographicArea` · `Standard` · `Technology` · `Disease` · `Vector` · `DateOrPeriod` · `Metric`

**20 relationship predicates:** `regulates` · `enforces` · `implements` · `operates` · `located_in` · `targets` · `measures` · `set_target` · `emits` · `treats_or_processes` · `causes` · `transmits` · `affects` · `collaborates_with` · `funded_by` · `succeeded_by` · `complies_with` · `achieved_metric` · `occurred_during` · `headed_by`

To adapt to a new domain, edit `output/ontology.json` and re-run from Stage 5.

---

## Graph Schema

```
(:Entity:<EntityType> {
    canonical_id,   // stable hash, merge key
    name,           // canonical display name
    aliases         // surface forms that resolved here
})

(subject)-[:<PREDICATE> {
    confidence,     // 0.0–1.0 from LLM
    evidence,       // verbatim quote ≤20 words from source
    source_doc,     // filename
    source_page,    // page number
    ontology_valid  // false = flagged for review
}]->(object)
```

---

## Project Structure

```
pdf-knowledge-graph-pipeline/
├── pdfs/                        # ← drop your PDFs here
├── output/
│   ├── extractions/             # one JSON per PDF (Stage 2)
│   ├── chunks.jsonl             # all chunks with provenance (Stage 3)
│   ├── ontology.json            # domain ontology (Stage 4)
│   ├── extractions.jsonl        # raw LLM triples (Stage 5)
│   ├── canonical_map.json       # entity resolution map (Stage 6)
│   ├── validated_triples.jsonl  # filtered triples (Stage 7)
│   └── validation_report.txt    # ontology violation audit (Stage 7)
├── pipeline/                    # stage modules + CLI runners
├── src/                         # Streamlit Graph-RAG app (original PoC)
├── run_overnight.sh             # watchdog for large collections
├── docker-compose.yml           # Neo4j 5.20 + APOC
└── .env.example                 # credential template
```

---

## Troubleshooting

**`Ollama is not reachable`** — Run `ollama serve` or open the Ollama app.

**Extraction is slow** — Switch to `qwen3:0.6b` in `.env`. Already-processed chunks are skipped automatically.

**High violation rate in validation report** — Expected with smaller models. Violations are kept (not dropped) so you can review and extend the ontology.

**Neo4j connection refused** — Run `docker compose up -d` and wait ~15 seconds.

**Scanned PDF produces no text** — Install Tesseract: `brew install tesseract && pip install pytesseract pdf2image`.

---

## Related Projects

- [`local-pdf-rag`](https://github.com/nawzaysfinah/local-pdf-rag) — simpler local RAG without the graph layer; better for Q&A over a small document set
- [`build-llm-apps`](https://github.com/nawzaysfinah/build-llm-apps) — beginner guide to building LLM apps, covering RAG fundamentals

---

*Built by [Syaz](https://syaz.super.site) — AI Lecturer @ ITE College West, Singapore*
