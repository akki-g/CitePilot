#AsyncDriver is Neo4js process safe connection pool object
# AsyncGraphDatabase is the factory that creates that driver
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings

def create_neo4j_driver(settings: Settings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        # in docker compose this is 'bolt://neo4j:7687', the neo4j service hostname
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

# the driver is analogous to sqlalchemys engine: expensive pooled and process wide
# dont create drivers per request; create once in fastapi lifespan and close on shutdown
# functions that need graph access reveive the driver and open short sessions

