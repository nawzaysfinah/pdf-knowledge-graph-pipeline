// ============================================================
// Neo4j Knowledge Graph Cleanup Queries
// Run each block independently in the Neo4j Browser or via cypher-shell.
// ============================================================


// ------------------------------------------------------------
// Query 1: Remove nodes with invalid entity types
// Deletes all nodes whose `type` property is not in the
// ontology entity_types list. DETACH DELETE removes all
// relationships connected to the deleted node as well.
// ------------------------------------------------------------
MATCH (n:Entity)
WHERE NOT n.type IN [
  'GovernmentAgency', 'Regulation', 'Policy', 'Programme',
  'Pollutant', 'WasteType', 'Facility', 'Organisation', 'Person',
  'EnvironmentalIndicator', 'ClimateEvent', 'GeographicArea',
  'Standard', 'Technology', 'Disease', 'Vector', 'DateOrPeriod', 'Metric'
]
DETACH DELETE n;


// ------------------------------------------------------------
// Query 2: Fix casing variants on node type property
// Corrects known casing inconsistencies introduced by
// smaller LLM models and early pipeline versions.
// ------------------------------------------------------------
MATCH (n:Entity) WHERE n.type = 'Organization'
SET n.type = 'Organisation';

MATCH (n:Entity) WHERE n.type = 'organisation'
SET n.type = 'Organisation';

MATCH (n:Entity) WHERE n.type = 'environmentalIndicator'
SET n.type = 'EnvironmentalIndicator';

MATCH (n:Entity) WHERE n.type = 'governmentagency'
SET n.type = 'GovernmentAgency';


// ------------------------------------------------------------
// Query 3: Delete relationships with invalid predicates
// Removes all relationships whose type is not in the
// ontology relationship_types list.
// ------------------------------------------------------------
MATCH ()-[r]->()
WHERE NOT type(r) IN [
  'REGULATES', 'ENFORCES', 'IMPLEMENTS', 'OPERATES', 'LOCATED_IN',
  'TARGETS', 'MEASURES', 'SET_TARGET', 'EMITS', 'TREATS_OR_PROCESSES',
  'CAUSES', 'TRANSMITS', 'AFFECTS', 'COLLABORATES_WITH', 'FUNDED_BY',
  'SUCCEEDED_BY', 'COMPLIES_WITH', 'ACHIEVED_METRIC',
  'OCCURRED_DURING', 'HEADED_BY'
]
DELETE r;


// ------------------------------------------------------------
// Query 4: Delete noise entity nodes
// Removes nodes whose name is too short, starts lowercase,
// contains newlines, or ends with a period — all signs of
// OCR artifacts or document boilerplate leaking in.
// ------------------------------------------------------------
MATCH (n:Entity)
WHERE
  size(n.name) < 4
  OR (n.name =~ '^[a-z].*')
  OR n.name CONTAINS '\n'
  OR n.name ENDS WITH '.'
DETACH DELETE n;


// ------------------------------------------------------------
// Query 5a: Merge NEA duplicate entities (APOC version)
// Requires APOC plugin. Merges "NEA" and
// "National Environmental Agency" into
// "National Environment Agency".
// Run Query 5b if APOC is not available.
// ------------------------------------------------------------
MATCH (canonical:Entity {name: 'National Environment Agency'})
MATCH (dup:Entity)
WHERE dup.name IN ['NEA', 'National Environmental Agency']
  AND dup <> canonical
CALL apoc.refactor.mergeNodes([canonical, dup], {
  properties: 'combine',
  mergeRels: true
})
YIELD node
SET node.name = 'National Environment Agency'
RETURN node.name, node.aliases;


// ------------------------------------------------------------
// Query 5b: Merge NEA duplicates (manual fallback, no APOC)
// Copies relationships from duplicates to canonical node,
// then deletes the duplicates.
// ------------------------------------------------------------
MATCH (canonical:Entity {name: 'National Environment Agency'})
MATCH (dup:Entity)
WHERE dup.name IN ['NEA', 'National Environmental Agency']
  AND dup <> canonical

// Re-point outgoing relationships
WITH canonical, dup
MATCH (dup)-[r]->(target)
WHERE target <> canonical
MERGE (canonical)-[r2:REGULATES]->(target)   // repeat block per predicate as needed
ON CREATE SET r2 = properties(r)

// Re-point incoming relationships
WITH canonical, dup
MATCH (source)-[r]->(dup)
WHERE source <> canonical
MERGE (source)-[r2:REGULATES]->(canonical)   // repeat block per predicate as needed
ON CREATE SET r2 = properties(r)

// Merge aliases and delete duplicate
WITH canonical, dup
SET canonical.aliases = canonical.aliases + [dup.name] + coalesce(dup.aliases, [])
DETACH DELETE dup;


// ------------------------------------------------------------
// Query 6: Add indexes for query performance
// Creates range indexes on the most-queried properties.
// IF NOT EXISTS makes this idempotent.
// ------------------------------------------------------------
CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name);
CREATE INDEX entity_type IF NOT EXISTS FOR (n:Entity) ON (n.type);


// ------------------------------------------------------------
// Query 7a: Verification — node count by type
// ------------------------------------------------------------
MATCH (n:Entity)
RETURN n.type AS type, count(n) AS count
ORDER BY count DESC;


// ------------------------------------------------------------
// Query 7b: Verification — relationship count by type
// ------------------------------------------------------------
MATCH ()-[r]->()
RETURN type(r) AS relationship, count(r) AS count
ORDER BY count DESC;


// ------------------------------------------------------------
// Query 7c: Verification — top 15 nodes by degree
// ------------------------------------------------------------
MATCH (n:Entity)
WITH n, size([(n)-[]-() | 1]) AS degree
RETURN n.name, n.type, degree
ORDER BY degree DESC
LIMIT 15;
