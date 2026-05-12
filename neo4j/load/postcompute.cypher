// Derived relationships for analytics widgets.

MATCH (:Topic)-[r:CO_OCCURS_WITH]->(:Topic)
DELETE r;

MATCH (d:Document)-[:MENTIONS]->(t:Topic)
WITH d, collect(DISTINCT t) AS topics
WHERE size(topics) > 1
UNWIND range(0, size(topics)-2) AS i
UNWIND range(i+1, size(topics)-1) AS j
WITH topics[i] AS t1, topics[j] AS t2, count(*) AS co_count
MERGE (t1)-[r:CO_OCCURS_WITH]->(t2)
SET r.count = co_count,
    r.score = toFloat(co_count);

MATCH (:Division)-[r:SHARES_LEARNING_WITH]->(:Division)
DELETE r;

MATCH (d1:Division)<-[:CREATED_BY]-(doc1:Document)-[:CAPTURES]->(l:Learning)<-[:CAPTURES]-(doc2:Document)-[:CREATED_BY]->(d2:Division)
WHERE id(d1) < id(d2)
WITH d1, d2, count(DISTINCT l) AS shared_count
WHERE shared_count > 0
MERGE (d1)-[r:SHARES_LEARNING_WITH]->(d2)
SET r.count = shared_count;
