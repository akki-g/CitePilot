import asyncio 

from app.config import get_settings
from app.db.postgres import create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver
from app.graph.schema import apply_constraints
from app.graph.sync import resync_graph


async def main() -> None:
    # parse env once
    settings = get_settings()

    # create temporary process-local clients
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    driver = create_neo4j_driver(settings)

    try:
        # constraints must exist before merge heavy sync work
        await apply_constraints(driver)

        # use 1 db session for the rebuild
        async with session_factory as session:
            await resync_graph(session, driver)

    finally:
        await driver.close()
        await engine.dispose()



if __name__ == "__main__":
    asyncio.run(main())