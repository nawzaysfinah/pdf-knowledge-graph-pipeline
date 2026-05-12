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
     │                          tables kept atomic
     ▼
output/chunks.jsonl
     │
     ▼
Stage 5 · LLM Triple Extraction Ollama (qwen3) + Agency ontology prompt
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
Stage 7 · Validation            confidence filter (< 0.7 dropped)
     │                          ontology type-constraint check (violations flagged)
     ▼
output/validated_triples.jsonl
output/validation_report.txt
     │
     ▼
Stage 8 · Neo4j Ingestion       MERGE nodes + relationships (idempotent)
     │                          dual labels (:Entity:<Type>)
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
| Ollama model | `qwen3:latest` | `ollama pull qwen3:latest` |
| Tesseract *(optional)* | any | only needed for scanned PDFs — `brew install tesseract` |

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
Edit `.env` if your Neo4j credentials differ.

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
python -m pipeline.run_extract          # Stage 2 — extract text + tables
python -m pipeline.run_chunk            # Stage 3 — chunk into semantic units
python -m pipeline.run_extract_triples  # Stage 5 — LLM triple extraction
python -m pipeline.run_resolve          # Stage 6 — entity resolution (interactive)
python -m pipeline.run_validate         # Stage 7 — validate + filter triples
python -m pipeline.run_ingest           # Stage 8 — write to Neo4j
python -m pipeline.run_smoke_tests      # Stage 9 — verify graph
```

### One-liner (auto-confirms entity merges)

```bash
python -m pipeline.run_extract          && \
python -m pipeline.run_chunk            && \
python -m pipeline.run_extract_triples  && \
echo "y" | python -m pipeline.run_resolve && \
python -m pipeline.run_validate         && \
python -m pipeline.run_ingest           && \
python -m pipeline.run_smoke_tests
```

> Remove `echo "y" |` if you want to review proposed entity merges before applying them.

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
│   └── validation_report.txt    # ontology violation audit (Stage 7)
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

Example: `(:Entity:GovernmentAgency {name: "the Agency", aliases: ["Agency"]})`

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
// All entities
MATCH (n:Entity) RETURN n.name, n.type ORDER BY n.type, n.name

// All relationships with evidence
MATCH (a:Entity)-[r]->(b:Entity)
RETURN a.name, type(r), b.name, r.evidence, r.confidence
ORDER BY r.confidence DESC

// Ontology violations to review
MATCH (a:Entity)-[r]->(b:Entity)
WHERE r.ontology_valid = false
RETURN a.name, type(r), b.name, r.violation, r.source_doc

// Most connected entities
MATCH (n:Entity)
WITH n, size([(n)-[]-() | 1]) AS degree
RETURN n.name, n.type, degree ORDER BY degree DESC LIMIT 10
```

---

## Troubleshooting

**`Ollama is not reachable`**
Ensure Ollama is running: `ollama serve` (or open the Ollama app).

**`No PDFs found in pdfs/`**
Copy PDFs with `cp`, not `cd`: `cp /path/to/file.pdf pdfs/`

**High violation rate in validation report**
Expected on short/simple documents. The model performs better with longer,
domain-rich PDF content. Violations are kept (not dropped) so you can review
them and optionally extend the ontology.

**Neo4j connection refused**
Run `docker compose up -d` from the project root and wait ~15 seconds for
the container to fully start.

**Scanned PDF produces no text**
Install Tesseract: `brew install tesseract`, then
`pip install pytesseract pdf2image`.

---

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
