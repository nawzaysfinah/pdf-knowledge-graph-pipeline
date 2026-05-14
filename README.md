# Agency Knowledge Graph — PDF Extraction Pipeline

End-to-end pipeline that extracts entities and relationships from Agency PDF
documents and ingests them as a queryable knowledge graph in Neo4j.

> The project also contains an earlier **Streamlit Graph-RAG app** (CSV-based,
> Ollama-powered) documented at the [bottom of this file](#streamlit-graph-rag-app).

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
     │                          entities {name, type, aliases}
     │                          triples {subject, predicate, object, evidence, confidence}
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
output/validation_report.txt
     │
     ▼
Stage 8 · Neo4j Ingestion       MERGE nodes + relationships (idempotent)
     │                          dual labels (:Entity:<Type>), label/predicate sanitization
     ▼
Neo4j  bolt://localhost:7687
     │
     ▼
Stage 9 · Smoke Tests           degree centrality, relationship explorer,
                                duplicate entity detector
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | |
| Docker Desktop | any | for Neo4j |
| Ollama | any | must be running locally |
| Ollama model | `qwen3:0.6b` | `ollama pull qwen3:0.6b` — fastest for extraction |
| Tesseract *(optional)* | any | only needed for scanned PDFs — `brew install tesseract` |

> **Model choice:** `qwen3:0.6b` (500 MB) is recommended for speed on local hardware.
> `qwen3:latest` (8B, 5 GB) produces higher quality but is ~30× slower without a GPU.

---

## Setup

### 1 — Clone and create virtual environment

```bash
cd <repo-folder>
python -m venv .venv
source .venv/bin/activate
```

### 2 — Install dependencies

```bash
# Streamlit app (original)
pip install -r requirements.txt

# PDF pipeline (new)
pip install -r requirements-pipeline.txt
```

### 3 — Configure environment

```bash
cp .env.example .env
```

The defaults work out of the box if you use the Docker Neo4j setup below.
Edit `.env` if your Neo4j credentials or Ollama model differ.

### 4 — Start Neo4j

```bash
docker compose up -d
```

Neo4j will be available at:
- **Bolt** `bolt://localhost:7687`
- **Browser** `http://localhost:7474`  (login: `neo4j` / `changeme`)

### 5 — Validate environment

```bash
python -m pipeline.validate_env
```

All imports and credentials should show `[OK]`.

---

## Processing PDFs

### Add PDFs

```bash
cp /path/to/document.pdf pdfs/
```

### Run the full pipeline

```bash
.venv/bin/python -m pipeline.run_extract          # Stage 2 — extract text + tables
.venv/bin/python -m pipeline.run_chunk            # Stage 3 — chunk into semantic units
.venv/bin/python -m pipeline.run_extract_triples  # Stage 5 — LLM triple extraction
echo "y" | .venv/bin/python -m pipeline.run_resolve  # Stage 6 — entity resolution
.venv/bin/python -m pipeline.run_validate         # Stage 7 — validate + filter triples
.venv/bin/python -m pipeline.run_ingest           # Stage 8 — write to Neo4j
.venv/bin/python -m pipeline.run_smoke_tests      # Stage 9 — verify graph
```

> Remove `echo "y" |` from Stage 6 if you want to review proposed entity merges interactively.

### Overnight / large-document runs

For large PDF collections, use the watchdog script which prevents system sleep,
auto-restarts Ollama if it crashes, and resumes extraction from the last checkpoint:

```bash
bash run_overnight.sh
```

The script logs progress to `output/overnight.log` and stops automatically when
all chunks are processed.

### Re-run behaviour

| Stage | On re-run |
|---|---|
| Extract (2) | Skips PDFs with unchanged checksum |
| Chunk (3) | Skips doc_ids already in `chunks.jsonl` |
| LLM Triples (5) | Skips chunk_ids already in `extractions.jsonl` |
| Resolve (6) | Re-clusters all entities; shows updated merge proposals |
| Validate (7) | Always rewrites `validated_triples.jsonl` fully |
| Ingest (8) | Always safe — `MERGE` is idempotent |

---

## Ontology

The Agency domain ontology lives at `output/ontology.json` and defines:

- **18 entity types** — `GovernmentAgency`, `Regulation`, `Policy`, `Programme`,
  `Pollutant`, `WasteType`, `Facility`, `Organisation`, `Person`,
  `EnvironmentalIndicator`, `ClimateEvent`, `GeographicArea`, `Standard`,
  `Technology`, `Disease`, `Vector`, `DateOrPeriod`, `Metric`

- **20 relationship predicates** — `regulates`, `enforces`, `implements`,
  `operates`, `located_in`, `targets`, `measures`, `set_target`, `emits`,
  `treats_or_processes`, `causes`, `transmits`, `affects`, `collaborates_with`,
  `funded_by`, `succeeded_by`, `complies_with`, `achieved_metric`,
  `occurred_during`, `headed_by`

To extend the ontology, edit `output/ontology.json` and re-run from Stage 5.

---

## Project Structure

```
<repo-folder>/
│
├── pdfs/                        # ← drop your PDFs here
│
├── output/
│   ├── extractions/             # one JSON per PDF (Stage 2)
│   ├── chunks.jsonl             # all chunks with provenance (Stage 3)
│   ├── ontology.json            # Agency domain ontology (Stage 4)
│   ├── extractions.jsonl        # raw LLM triples (Stage 5)
│   ├── canonical_map.json       # entity resolution map (Stage 6)
│   ├── validated_triples.jsonl  # filtered + validated triples (Stage 7)
│   ├── validation_report.txt    # ontology violation audit (Stage 7)
│   └── overnight.log            # watchdog run log (run_overnight.sh)
│
├── pipeline/
│   ├── validate_env.py          # Stage 1 — environment check
│   ├── pdf_extractor.py         # Stage 2 — PDF extraction logic
│   ├── run_extract.py           # Stage 2 — CLI runner
│   ├── chunker.py               # Stage 3 — chunking logic
│   ├── run_chunk.py             # Stage 3 — CLI runner
│   ├── ontology.py              # Stage 4 — ontology loader + validator
│   ├── triple_extractor.py      # Stage 5 — LLM extraction logic
│   ├── run_extract_triples.py   # Stage 5 — CLI runner
│   ├── entity_resolver.py       # Stage 6 — entity resolution logic
│   ├── run_resolve.py           # Stage 6 — CLI runner (interactive)
│   ├── validator.py             # Stage 7 — validation + filtering logic
│   ├── run_validate.py          # Stage 7 — CLI runner
│   ├── neo4j_ingester.py        # Stage 8 — Neo4j ingestion logic
│   ├── run_ingest.py            # Stage 8 — CLI runner
│   ├── smoke_tests.py           # Stage 9 — Cypher smoke queries
│   └── run_smoke_tests.py       # Stage 9 — CLI runner
│
├── run_overnight.sh             # Overnight watchdog (sleep prevention + auto-restart)
├── src/                         # Streamlit Graph-RAG app (see below)
├── docker-compose.yml           # Neo4j 5.20 + APOC
├── requirements.txt             # Streamlit app dependencies
├── requirements-pipeline.txt    # PDF pipeline dependencies
└── .env.example                 # credential template
```

---

## Neo4j Graph Model

### Nodes

```
(:Entity:<EntityType> {
    canonical_id,   // stable hash id, merge key
    name,           // canonical display name
    type,           // entity type string
    aliases         // list of surface forms that resolved here
})
```

Example: `(:Entity:GovernmentAgency {name: "National Environment Agency", aliases: ["NEA"]})`

### Relationships

```
(subject)-[:<PREDICATE> {
    predicate,      // original ontology predicate name
    confidence,     // 0.0–1.0 from LLM
    evidence,       // verbatim quote ≤20 words from source text
    source_doc,     // filename
    source_page,    // page number
    chunk_id,       // traceability to source chunk
    ontology_valid, // boolean — false = violation flagged for review
    violation       // violation description if ontology_valid = false
}]->(object)
```

### Useful Cypher queries

```cypher
// Most connected entities
MATCH (n:Entity)
WITH n, size([(n)-[]-() | 1]) AS degree
RETURN n.name, n.type, degree ORDER BY degree DESC LIMIT 20

// All relationships with evidence
MATCH (a:Entity)-[r]->(b:Entity)
RETURN a.name, type(r), b.name, r.evidence, r.confidence
ORDER BY r.confidence DESC

// Ontology violations to review
MATCH (a:Entity)-[r]->(b:Entity)
WHERE r.ontology_valid = false
RETURN a.name, type(r), b.name, r.violation, r.source_doc

// Subgraph around a specific entity
MATCH p=(n:Entity {name: "National Environment Agency"})-[*1..2]-(m:Entity)
RETURN p LIMIT 50
```

---

## Extraction Quality Controls

### Valid entity types

The ontology enforces exactly 18 entity types. The LLM prompt and
post-processing validation both reject any entity that does not use one of:

`GovernmentAgency` · `Regulation` · `Policy` · `Programme` · `Pollutant` ·
`WasteType` · `Facility` · `Organisation` · `Person` · `EnvironmentalIndicator` ·
`ClimateEvent` · `GeographicArea` · `Standard` · `Technology` · `Disease` ·
`Vector` · `DateOrPeriod` · `Metric`

### Valid relationship predicates

Exactly 20 predicates are accepted:

`regulates` · `enforces` · `implements` · `operates` · `located_in` · `targets` ·
`measures` · `set_target` · `emits` · `treats_or_processes` · `causes` ·
`transmits` · `affects` · `collaborates_with` · `funded_by` · `succeeded_by` ·
`complies_with` · `achieved_metric` · `occurred_during` · `headed_by`

### Running the post-extraction cleaner (Stage 7a)

```bash
# Dry run — report only, no files written
.venv/bin/python -m pipeline.validate_extractions --dry-run

# Full run — writes output/validated_extractions.jsonl
.venv/bin/python -m pipeline.validate_extractions
```

Stage 7 (`run_validate`) now runs this automatically before the confidence
filter step, so you only need to call it manually for diagnostics.

### Running Neo4j cleanup

Open **http://localhost:7474**, paste and run each block from
`neo4j_cleanup.cypher` independently:

| Query | Effect |
|---|---|
| Q1 | Delete nodes with invalid entity types |
| Q2 | Fix casing variants (`Organization` → `Organisation`, etc.) |
| Q3 | Delete relationships with invented predicates |
| Q4 | Delete noise nodes (short names, lowercase start, OCR artifacts) |
| Q5a/5b | Merge NEA duplicate nodes (APOC or manual fallback) |
| Q6 | Create performance indexes |
| Q7a–7c | Verify cleanup results |

### Known issues found and fixed

| Issue | Fix |
|---|---|
| LLM inventing predicates outside ontology | Prompt rule 2 + `validate_extractions.py` triple filter |
| LLM inventing entity types outside ontology | Prompt rule 1 + `validate_extractions.py` entity filter |
| Entity names being full sentences | Prompt rule 3 (max 8 words, max 60 chars) + name validator |
| Document boilerplate leaking as entities | Prompt rule 4 (skip TOC/headers/GRI blocks) + blocklist |
| OCR artifacts as entity types | `validate_extractions.py` entity type filter + Q1 cleanup |
| Spelling/casing duplicates | Q2 Cypher fix + entity resolver alias merge |
| Neo4j labels crashing on special chars | `neo4j_ingester._safe_label()` sanitization |

---

## Troubleshooting

**`Ollama is not reachable`**
Ensure Ollama is running: `ollama serve` (or open the Ollama app).

**`No PDFs found in pdfs/`**
Copy PDFs with `cp`, not `cd`: `cp /path/to/file.pdf pdfs/`

**Extraction is very slow**
Switch to a smaller model. `qwen3:0.6b` runs ~30× faster than `qwen3:latest` on CPU.
Update `OLLAMA_MODEL` in `.env` and restart extraction — already-processed chunks are skipped.

**High violation rate in validation report**
Expected with smaller models or short documents. Violations are kept (not dropped)
so you can review and optionally extend the ontology.

**Neo4j connection refused**
Run `docker compose up -d` from the project root and wait ~15 seconds for
the container to fully start.

**Scanned PDF produces no text**
Install Tesseract: `brew install tesseract`, then
`pip install pytesseract pdf2image`.

---

## Streamlit Graph-RAG App

The original PoC for CSV-based ingestion with a human review queue and
evidence-first Graph-RAG chat.

### Run

```bash
streamlit run src/app.py
```

### Architecture

```
Raw CSVs (data/raw) + mapping_config.yaml
        → Canonicalization (src/io)
        → Neo4j Loader (src/graph/loader.py)
        → Triple Extraction (Ollama, src/llm/extract_triples.py)
        → Review Queue (SQLite)
        → Neo4j
        → Dashboard / Explorer / Ask / Report (Streamlit)
```

See `neo4j/schema.md` for the CSV pipeline graph schema.
Sample data is provided under `data/sample/` (30 docs, 3 divisions, 6 initiatives).
