from datetime import datetime, timedelta
import logging
from typing import Optional
from uuid import uuid4
from sqlalchemy import select
# removed
from ..models import YandexUser

logger = logging.getLogger(__name__)

async def save_account(user_id: str, ya_user_id: Optional[str], access_token: str, refresh_token: Optional[str], expires_in: Optional[int]):
    """Сохранить пользователя в базу данных."""
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=int(expires_in))
        except Exception:
            expires_at = None

    async with self.plugin.get_session() as db:
        existing = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
        user = existing.scalar_one_or_none()
        if user is None:
            user = YandexUser(
                id=str(uuid4()),
                user_id=user_id,
                ya_user_id=ya_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )
            db.add(user)
        else:
            user.access_token = access_token
            user.refresh_token = refresh_token
            user.ya_user_id = ya_user_id or user.ya_user_id
            user.expires_at = expires_at
        await db.commit()


async def save_user_info(user_id: str, user_info_data: dict):
    """
    Сохранить полную информацию об умном доме (devices, groups, scenarios) в базу данных.
    
    Args:
        user_id: ID пользователя
        user_info_data: Данные из /v1.0/user/info
    """
    try:
        async with self.plugin.get_session() as db:
            res = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
            account = res.scalar_one_or_none()
            if account:
                if not account.config:
                    account.config = {}
                account.config.update({
                    'user_info': {
                        'devices': user_info_data.get('devices', []),
                        'groups': user_info_data.get('groups', []),
                        'scenarios': user_info_data.get('scenarios', []),
                        'synced_at': datetime.utcnow().isoformat()
                    }
                })
                await db.commit()
                logger.info(f"Saved user info (devices, groups, scenarios) for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to save user info for user {user_id}: {e}")
