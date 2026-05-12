# Agency Graph Schema

## Nodes
- `Document {doc_id, title, text, date, doc_type, source_uri}`
- `Division {division_id, name}`
- `Initiative {initiative_id, name, description}`
- `Topic {topic_id, name}`
- `Issue {issue_id, name}`
- `Learning {learning_id, text}`
- `Outcome {outcome_id, name}`

## Core Relationships
- `(Document)-[:CREATED_BY]->(Division)`
- `(Initiative)-[:OWNED_BY]->(Division)`
- `(Document)-[:ABOUT]->(Initiative)`
- `(Document)-[:MENTIONS]->(Topic)`
- `(Document)-[:CAPTURES]->(Learning)`
- `(Learning)-[:RELATES_TO]->(Topic)`
- `(Learning)-[:ADDRESSES]->(Issue)`
- `(Initiative)-[:ADDRESSES]->(Issue)`
- `(Initiative)-[:RESULTED_IN]->(Outcome)`

## Derived Relationships
- `(Topic)-[:CO_OCCURS_WITH {count, score}]->(Topic)`
- `(Division)-[:SHARES_LEARNING_WITH {count}]->(Division)`

## Notes
- Canonical tables are loaded via `src/graph/loader.py`.
- Optional tables (`divisions`, `initiatives`, `doc_initiatives`) may be empty.
- If divisions table is missing, divisions are derived from `documents.division` values.
- The review queue is mandatory before LLM-extracted triples are persisted to graph.
