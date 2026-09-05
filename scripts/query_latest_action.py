import asyncio
from sqlalchemy import select, desc
from app.infrastructure.database import async_session_factory
from app.domain.action import Action, ExecutionAttempt

async def main():
    async with async_session_factory() as session:
        act = (await session.execute(
            select(Action).order_by(desc(Action.created_at)).limit(1)
        )).scalar_one_or_none()
        print('ACTION:', act.action_type if act else None)
        print('STATUS:', act.status if act else None)
        if act:
            att = (await session.execute(
                select(ExecutionAttempt)
                .where(ExecutionAttempt.action_id == act.id)
                .order_by(desc(ExecutionAttempt.started_at))
            )).scalars().first()
            print('PROVIDER:', att.provider_request_id if att else None)
            short_url = None
            if att and att.attempt_metadata:
                short_url = att.attempt_metadata.get('short_url')
            print('SHORT_URL:', short_url)

asyncio.run(main())
