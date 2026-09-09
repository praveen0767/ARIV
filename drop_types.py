import asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.async_database_url)
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP TYPE IF EXISTS recovery_outcome_status CASCADE"))
        await conn.execute(sa.text("DROP TYPE IF EXISTS recovery_source_type CASCADE"))
        await conn.execute(sa.text("DROP TYPE IF EXISTS experiment_status CASCADE"))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
