// ============================================================
// Selective Delete — Run MANUALLY after reviewing soft_cleanup output.
// Each block is independent. Edit lists before running.
// ============================================================


// ------------------------------------------------------------
// Step 1: Delete pure noise relationships
// Run ONLY after reviewing soft_cleanup Query 7 output.
// Edit the list to remove any predicates you want to KEEP.
// ------------------------------------------------------------
MATCH ()-[r]->()
WHERE type(r) IN [
  'MR', 'MS', 'O', 'IN', 'OF', 'AT',
  'LIMIT7', 'REL_41', 'REL_103_1', 'REL_103_2', 'REL_103_3',
  'ARE', 'IS_AGO', 'HAS_FOREWORD', 'WILL_NOT_BE_PRINTED',
  'CAN_BE_FOUND_ON', 'INTENTIONALLY_OMITTED'
]
DELETE r;


// ------------------------------------------------------------
// Step 2: Delete confirmed noise nodes (tiny names only)
// Run ONLY after reviewing soft_cleanup Query 3 output.
// Only removes nodes with names shorter than 4 characters.
// ------------------------------------------------------------
MATCH (n)
WHERE n.flagged = true
  AND n.flag_reason = 'invalid_entity_name'
  AND size(n.name) < 4
DETACH DELETE n;


// ------------------------------------------------------------
// Step 3: Unflag relationships you decide to keep
// For predicates you reviewed and want to retain as-is.
// Edit the predicate list to match what you want to keep.
// ------------------------------------------------------------
MATCH ()-[r]->()
WHERE type(r) IN [
  'LAUNCHED', 'SIGNED', 'ESTABLISHED', 'HEADED_BY',
  'WORKS_FOR', 'INTRODUCED', 'LEADS', 'MANAGES',
  'SUPPORTS', 'DEVELOPS', 'UNDERTAKES', 'PROMOTES',
  'ADMINISTERS', 'OVERSEES', 'APPOINTED', 'AWARDED'
]
REMOVE r.flagged, r.flag_reason;
