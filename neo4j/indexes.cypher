CREATE INDEX division_name IF NOT EXISTS FOR (n:Division) ON (n.name);
CREATE INDEX initiative_name IF NOT EXISTS FOR (n:Initiative) ON (n.name);
CREATE INDEX topic_name IF NOT EXISTS FOR (n:Topic) ON (n.name);
CREATE INDEX issue_name IF NOT EXISTS FOR (n:Issue) ON (n.name);
CREATE INDEX document_date IF NOT EXISTS FOR (n:Document) ON (n.date);
CREATE INDEX document_doc_type IF NOT EXISTS FOR (n:Document) ON (n.doc_type);
