"""Route handlers for Yandex Smart Home plugin."""
import logging
from typing import Dict, Any, Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from ..api.utils import cfg_get
from ..models import YandexUser

logger = logging.getLogger(__name__)


class RouteHandlers:
    """Handlers for all plugin routes."""

    def __init__(self, plugin_instance):
        """Initialize handlers with plugin instance reference."""
        self.plugin = plugin_instance
        self.db_session = plugin_instance.db_session_maker if hasattr(plugin_instance, 'db_session_maker') else None
        self.logger = logging.getLogger(__name__)

    async def list_devices_proxy(self, request: Request = None, user_id: str = None):
        """Proxy to list Yandex devices."""
        
        access_token = None
        try:
            if not user_id and request:
                user_id = await self.plugin._get_current_user_id(request)
            
            if user_id:
                async with self.plugin.get_session() as db:
                    res = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
                    acc = res.scalar_one_or_none()
                    if acc:
                        access_token = acc.access_token
        except Exception as e:
            self.logger.warning(f"Could not get access token: {e}")
        
        if not access_token:
            raise HTTPException(status_code=400, detail='Yandex token not configured')

        try:
            devices_data = await self.plugin.api_client.get_devices(access_token)
            
            # Возвращаем полные данные устройств с capabilities и properties
            # Это нужно для синхронизации статусов и состояний
            if isinstance(devices_data, dict):
                return JSONResponse(devices_data)
            elif isinstance(devices_data, list):
                return JSONResponse({'devices': devices_data})
            else:
                return JSONResponse({'devices': []})
        except Exception as e:
            raise HTTPException(status_code=502, detail=f'Yandex API error: {str(e)}')

    async def execute_action(self, payload: dict, request: Request = None):
        """Execute action on Yandex device."""
        
        self.logger.info(f"📥 execute_action called with payload: {payload}")
        
        device_id = payload.get('device_id')
        if not device_id:
            raise HTTPException(status_code=400, detail='device_id required')

        action = payload.get('action', 'execute')
        params = payload.get('params', payload)
        
        user_id = None
        if request:
            try:
                user_id = await self.plugin._get_current_user_id(request)
                self.logger.info(f"👤 User ID from request: {user_id}")
            except Exception as e:
                self.logger.warning(f"⚠️ Could not get user_id from request: {e}")
        
        if not user_id:
            user_id = payload.get('user_id')
            self.logger.info(f"👤 User ID from payload: {user_id}")
        
        # Get user's access token
        access_token = None
        if user_id:
            async with self.plugin.get_session() as db:
                account_result = await db.execute(
                    select(YandexUser).where(YandexUser.user_id == user_id)
                )
                account = account_result.scalar_one_or_none()
                if account and account.access_token:
                    access_token = account.access_token
                    self.logger.info(f"✅ Got user-specific access token for user {user_id}")
                else:
                    self.logger.warning(f"⚠️ No Yandex account linked for user {user_id}")
        
        if not access_token:
            from ..auth.manager import YandexAuthManager
            self.logger.warning(f"⚠️ Using global token (fallback)")
            access_token = await YandexAuthManager.get_yandex_token()
        
        if not access_token:
            self.logger.error(f"❌ No access token available")
            raise HTTPException(status_code=400, detail='Yandex token not configured. Please link your Yandex account.')
        
        # Handle toggle action
        if action == 'toggle':
            self.logger.info(f"🔄 Toggle requested for device {device_id}")
            current_state = await self.plugin.state_manager.get_device_state(access_token, device_id, self.plugin.api_client)
            current_on = current_state.get('on', False)
            params['on'] = not current_on
            self.logger.info(f"🔄 Toggle: current={current_on} → new={not current_on}")
        
        self.logger.info(f"🚀 Sending command: device={device_id}, action={action}, params={params}")
        result = await self.plugin.device_manager.send_command(access_token, device_id, action, params)
        self.logger.info(f"✅ Command completed successfully")
        return JSONResponse({ 'status': 'ok', 'yandex_response': result })
