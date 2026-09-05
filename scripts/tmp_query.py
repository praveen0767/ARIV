import asyncio
from sqlalchemy import select, desc
from app.infrastructure.database import async_session_factory
from app.domain.action import Action, ExecutionAttempt

async def main():
    async with async_session_factory() as session:
        act = (await session.execute(
            select(Action)
            .where(Action.action_type == 'GENERATE_PAYMENT_LINK')
            .order_by(desc(Action.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if not act:
            print('No action')
            return
        att = (await session.execute(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.action_id == act.id)
            .order_by(desc(ExecutionAttempt.started_at))
            .limit(1)
        )).scalar_one_or_none()
        print('EVENT_ID:', act.id)
        print('CASE_ID:', act.case_id)
        print('ACTION:', act.action_type.value)
        print('ACTION_STATUS:', act.status.value)
        print('PROVIDER:', att.provider_request_id if att else None)
        print('SHORT_URL:', (att.attempt_metadata or {}).get('short_url') if att else None)

asyncio.run(main())
