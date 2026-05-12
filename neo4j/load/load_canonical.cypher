// Optional direct CSV import script for Neo4j import directory usage.
// Prefer Python loader for day-to-day use.

LOAD CSV WITH HEADERS FROM 'file:///canonical_documents.csv' AS row
MERGE (d:Document {doc_id: row.doc_id})
SET d.title = row.title,
    d.text = row.text,
    d.date = row.date,
    d.doc_type = row.doc_type,
    d.source_uri = row.source_uri;

LOAD CSV WITH HEADERS FROM 'file:///canonical_divisions.csv' AS row
MERGE (div:Division {division_id: row.division_id})
SET div.name = row.name;

LOAD CSV WITH HEADERS FROM 'file:///canonical_initiatives.csv' AS row
MERGE (i:Initiative {initiative_id: row.initiative_id})
SET i.name = row.name,
    i.description = row.description;

LOAD CSV WITH HEADERS FROM 'file:///canonical_doc_initiatives.csv' AS row
MATCH (d:Document {doc_id: row.doc_id})
MATCH (i:Initiative {initiative_id: row.initiative_id})
MERGE (d)-[:ABOUT]->(i);

MATCH (d:Document)
WHERE d.division IS NOT NULL AND trim(d.division) <> ''
MERGE (div:Division {division_id: 'division_' + replace(toLower(d.division), ' ', '_')})
SET div.name = d.division
MERGE (d)-[:CREATED_BY]->(div);
