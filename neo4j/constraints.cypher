CREATE CONSTRAINT document_doc_id IF NOT EXISTS
FOR (n:Document) REQUIRE n.doc_id IS UNIQUE;

CREATE CONSTRAINT division_division_id IF NOT EXISTS
FOR (n:Division) REQUIRE n.division_id IS UNIQUE;

CREATE CONSTRAINT initiative_initiative_id IF NOT EXISTS
FOR (n:Initiative) REQUIRE n.initiative_id IS UNIQUE;

CREATE CONSTRAINT topic_topic_id IF NOT EXISTS
FOR (n:Topic) REQUIRE n.topic_id IS UNIQUE;

CREATE CONSTRAINT issue_issue_id IF NOT EXISTS
FOR (n:Issue) REQUIRE n.issue_id IS UNIQUE;

CREATE CONSTRAINT learning_learning_id IF NOT EXISTS
FOR (n:Learning) REQUIRE n.learning_id IS UNIQUE;

CREATE CONSTRAINT outcome_outcome_id IF NOT EXISTS
FOR (n:Outcome) REQUIRE n.outcome_id IS UNIQUE;
