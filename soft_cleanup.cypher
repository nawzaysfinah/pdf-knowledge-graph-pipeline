// ============================================================
// Soft Cleanup — Tag problems for review. No DELETE anywhere.
// Run each block independently in Neo4j Browser.
// ============================================================


// ------------------------------------------------------------
// Query 1: Tag relationships outside the ontology
// Flags non-ontology predicates with flagged=true.
// Keeps them intact so you can decide what to do later.
// ------------------------------------------------------------
MATCH ()-[r]->()
WHERE NOT type(r) IN [
  'REGULATES','ENFORCES','IMPLEMENTS','OPERATES','LOCATED_IN',
  'TARGETS','MEASURES','SET_TARGET','EMITS','TREATS_OR_PROCESSES',
  'CAUSES','TRANSMITS','AFFECTS','COLLABORATES_WITH','FUNDED_BY',
  'SUCCEEDED_BY','COMPLIES_WITH','ACHIEVED_METRIC',
  'OCCURRED_DURING','HEADED_BY'
]
SET r.flagged = true, r.flag_reason = 'predicate_not_in_ontology'
RETURN type(r), count(r) AS count
ORDER BY count DESC;


// ------------------------------------------------------------
// Query 2: Tag nodes with invalid entity types
// Flags nodes whose type is not in the 18-type ontology.
// Does not delete them.
// ------------------------------------------------------------
MATCH (n)
WHERE NOT n.type IN [
  'GovernmentAgency','Regulation','Policy','Programme','Pollutant',
  'WasteType','Facility','Organisation','Person',
  'EnvironmentalIndicator','ClimateEvent','GeographicArea',
  'Standard','Technology','Disease','Vector','DateOrPeriod','Metric'
]
SET n.flagged = true, n.flag_reason = 'type_not_in_ontology'
RETURN n.type, count(n) AS count
ORDER BY count DESC;


// ------------------------------------------------------------
// Query 3: Tag noise entity names
// Flags nodes with short, lowercase, multi-word, or artifact names.
// Does not delete them.
// ------------------------------------------------------------
MATCH (n)
WHERE size(n.name) < 4
   OR n.name =~ '^[a-z].*'
   OR n.name CONTAINS '\n'
   OR n.name ENDS WITH '.'
   OR size(split(n.name, ' ')) > 9
SET n.flagged = true, n.flag_reason = 'invalid_entity_name'
RETURN count(n) AS flagged_noise_nodes;


// ------------------------------------------------------------
// Query 4: Fix known casing variants (SET only, no DELETE)
// Corrects LLM casing inconsistencies in place.
// ------------------------------------------------------------
MATCH (n {type: 'Organization'}) SET n.type = 'Organisation';
MATCH (n {type: 'environmentalIndicator'}) SET n.type = 'EnvironmentalIndicator';
MATCH (n {type: 'organisation'}) SET n.type = 'Organisation';
MATCH (n {type: 'governmentagency'}) SET n.type = 'GovernmentAgency';


// ------------------------------------------------------------
// Query 5: Review summary — flagged vs clean
// ------------------------------------------------------------
MATCH (n)
RETURN
  n.flagged IS NOT NULL AS is_flagged,
  count(n) AS node_count;

MATCH ()-[r]->()
RETURN
  r.flagged IS NOT NULL AS is_flagged,
  count(r) AS rel_count;


// ------------------------------------------------------------
// Query 6: Spot-check flagged relationships (sample)
// ------------------------------------------------------------
MATCH (a)-[r]->(b)
WHERE r.flagged = true
RETURN a.name, type(r), b.name, r.flag_reason
LIMIT 50;


// ------------------------------------------------------------
// Query 0: Delete self-referential loops (safe to run anytime)
// Removes relationships where a node points to itself.
// elementId() is preferred over the deprecated id() in Neo4j 5.x
// ------------------------------------------------------------
MATCH (n)-[r]->(n)
DELETE r;


// ------------------------------------------------------------
// Query 7: Flagged predicates with counts — decide what to keep
// Some non-ontology predicates (LAUNCHED, SIGNED, ESTABLISHED)
// may be worth keeping. Review here before selective_delete.
// ------------------------------------------------------------
MATCH ()-[r]->()
WHERE r.flagged = true
RETURN type(r) AS predicate, count(r) AS count
ORDER BY count DESC;
