// Paper UUID from Postgres is unique in Neo4j.
CREATE CONSTRAINT paper_id_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.id IS UNIQUE;

// OpenAlex work IDs are unique when present.
CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE;

// Author UUID mirrors Postgres.
CREATE CONSTRAINT author_id_unique IF NOT EXISTS
FOR (a:Author) REQUIRE a.id IS UNIQUE;

// Concepts are normalized by name for MVP.
CREATE CONSTRAINT concept_name_unique IF NOT EXISTS
FOR (c:Concept) REQUIRE c.name IS UNIQUE;

// Speeds year filtering/sorting in graph queries.
CREATE INDEX paper_year_index IF NOT EXISTS FOR (p:Paper) ON (p.year);

// Speeds finding/rendering stub papers.
CREATE INDEX paper_stub_index IF NOT EXISTS FOR (p:Paper) ON (p.is_stub);