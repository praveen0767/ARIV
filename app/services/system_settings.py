from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.system_settings import SystemSetting

class SystemSettingsService:
    @staticmethod
    async def get_setting(session: AsyncSession, key: str, default: str = None) -> Optional[str]:
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting is None:
            return default
            
        return setting.value
