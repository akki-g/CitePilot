# applied idempotently at every startup. Uniqueness contraints double as indexes, without them, every MERGE(p:Paper) is a full graph scan

from neo4j import AsyncDriver
# the driver type is used for the startup function signature

# these are the idempotent DDL statements, they can run every startup safely
CONSTRAINT_STATEMENTS = [
    # Paper UUID from Postgres is the canonical identity in Neo4j.
    "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.id IS UNIQUE",
    # OpenAlex ID is also unique when present, useful for import lookup/debugging.
    "CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE",
    # Author UUID mirrors Postgres author identity.
    "CREATE CONSTRAINT author_id_unique IF NOT EXISTS "
    "FOR (a:Author) REQUIRE a.id IS UNIQUE",
    # Concepts are normalized by name for MVP.
    "CREATE CONSTRAINT concept_name_unique IF NOT EXISTS "
    "FOR (c:Concept) REQUIRE c.name IS UNIQUE",
    # Year index helps graph views filter/sort papers by publication year.
    "CREATE INDEX paper_year_index IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    # Stub index helps UI/retrieval distinguish incomplete imported references.
    "CREATE INDEX paper_stub_index IF NOT EXISTS FOR (p:Paper) ON (p.is_stub)",
]

async def apply_constraints(driver: AsyncDriver) -> None:
    # open one short lived write sessoin for schema setup
    async with driver.session() as session:
        # run statements one at a time so failures are easy to spot
        for statement in CONSTRAINT_STATEMENTS:
            await session.run(statement)


# constraints prevent duplicate graph nodes and also create indexes for fast MERGE
# IF NOT EXISTS makes startup repeatable across restarts
