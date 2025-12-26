"""
Yandex Smart Home Plugin - OAuth integration and device synchronization.
Refactored to use modular structure.
"""
import asyncio
import logging
import json
import os
import http.client
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse

from sqlalchemy import select
from home_console_sdk.plugin import InternalPluginBase

# Import modular components
from .models import YandexUser
from .auth.manager import YandexAuthManager
from .api import YandexAPIClient, parse_last_updated, cfg_get
from .devices.manager import DeviceManager
from .state.state_manager import DeviceStateManager
from .handlers import RouteHandlers, AuthHandler, DeviceHandlers, AliceHandlers, IntentHandlers
from .service import save_account

# No direct core_service imports - all dependencies via DI

logger = logging.getLogger(__name__)


class YandexSmartHomePlugin(InternalPluginBase):
    """Yandex Smart Home plugin with OAuth and device synchronization."""

    id = "yandex_smart_home"
    name = "Yandex Smart Home"
    version = "0.4.0"
    description = "Yandex Smart Home adapter - OAuth + device sync + intent mapping + auth integration"

    async def on_load(self):
        """Initialize plugin."""
        self.router = APIRouter()
        
        # Ensure config exists
        if not hasattr(self, "config") or self.config is None:
            self.config = {}
        
        self.logger.info(f"🔧 YandexSmartHome plugin config on load: {self.config}")

        # Get get_current_user function from app.state for authentication
        self.get_current_user_fn = getattr(self.app.state, 'get_current_user', None)
        if not self.get_current_user_fn:
            self.logger.warning("get_current_user not available in app.state - user authentication may not work")

        # Models are injected via SDK (self.models) - no need for separate core_models

        # Create plugin tables (use engine from db_session_maker)
        try:
            from .models import Base as yandex_base
            # Get engine from session maker
            engine = self.db_session_maker.kw.get('bind')
            if engine:
                async with engine.begin() as conn:
                    await conn.run_sync(yandex_base.metadata.create_all)
        except Exception as e:
            self.logger.warning(f"Could not create tables for Yandex Smart Home: {e}")

        # Initialize managers with db_session_maker
        self.api_client = YandexAPIClient(self.config)
        # Pass Device model to state manager via DI
        device_model = self.models.get('Device')
        # Получаем online_timeout из конфигурации плагина (глобальная настройка из ядра)
        online_timeout = self.config.get('device_online_timeout', 300)  # По умолчанию 5 минут
        self.state_manager = DeviceStateManager(
            self.db_session_maker, 
            parse_last_updated, 
            self.logger, 
            device_model,
            online_timeout=online_timeout
        )
        self.device_manager = DeviceManager(self.db_session_maker, self.api_client, self.state_manager, self.config, models=self.models)
        # Pass plugin instance (which now has core_models and db_session_maker)
        self.route_handlers = RouteHandlers(self)
        self.auth_handlers = AuthHandler(self)
        self.device_handlers = DeviceHandlers(self)
        self.alice_handlers = AliceHandlers(self)
        self.intent_handlers = IntentHandlers(self)

        # Register routes
        self.router.add_api_route("/auth/start", self.auth_handlers.start_oauth, methods=["GET"])
        self.router.add_api_route("/callback", self.auth_handlers.oauth_callback, methods=["GET", "POST"])
        self.router.add_api_route("/auth/status", self.auth_handlers.auth_status, methods=["GET"])
        self.router.add_api_route("/auth/unlink", self.auth_handlers.auth_unlink, methods=["POST"])
        self.router.add_api_route("/devices", self.route_handlers.list_devices_proxy, methods=["GET"])
        self.router.add_api_route("/action", self.route_handlers.execute_action, methods=["POST"])

        # Device sync routes
        self.router.add_api_route("/sync", self.device_handlers.sync_devices, methods=["POST"])
        self.router.add_api_route("/sync_states", self.device_handlers.sync_device_states, methods=["POST"])
        self.router.add_api_route("/discover", self.device_handlers.auto_discover_new_devices, methods=["POST"])
        self.router.add_api_route("/bindings", self.device_handlers.list_bindings, methods=["GET"])
        self.router.add_api_route("/bindings", self.device_handlers.create_binding, methods=["POST"])

        # Alice and intent routes
        self.router.add_api_route("/alice", self.alice_handlers.handle_alice_request, methods=["POST"])
        self.router.add_api_route("/intents", self.intent_handlers.list_intents, methods=["GET"])
        self.router.add_api_route("/intents", self.intent_handlers.create_intent, methods=["POST"])
        self.router.add_api_route("/intents/{intent_name}", self.intent_handlers.update_intent, methods=["PUT"])
        self.router.add_api_route("/intents/{intent_name}", self.intent_handlers.delete_intent, methods=["DELETE"])
        
        # ========== SUBSCRIBE TO DEVICE EVENTS ==========
        # Подписываемся на события устройств для обработки команд
        try:
            await self.events.subscribe("device.*.turn_on", self._handle_device_execute_event)
            await self.events.subscribe("device.*.turn_off", self._handle_device_execute_event)
            await self.events.subscribe("device.*.toggle", self._handle_device_execute_event)
            await self.events.subscribe("device.*.execute", self._handle_device_execute_event)
            self.logger.info("✅ Subscribed to device execute events")
        except Exception as e:
            self.logger.error(f"❌ Failed to subscribe to events: {e}", exc_info=True)
        
        # ========== PERIODIC SYNC TASK ==========
        # Запускаем периодическую синхронизацию устройств
        # Используем device_poll_interval из глобальной конфигурации, если не задан sync_interval
        sync_interval = self.config.get('sync_interval') or self.config.get('device_poll_interval', 300)
        if sync_interval and sync_interval > 0:
            # Проверяем, не добавлена ли уже задача (защита от дублирования)
            existing_task = self.tasks.get_task("periodic_sync")
            if not existing_task:
                self.logger.info(f"🔄 Starting periodic device sync (interval: {sync_interval}s, from config: device_poll_interval={self.config.get('device_poll_interval', 'not set')})")
                self.tasks.add_task(
                    "periodic_sync",
                    self._periodic_sync_all_users,
                    interval=float(sync_interval)
                )
            else:
                self.logger.debug("Periodic sync task already exists, skipping")
        else:
            self.logger.info("⏸️ Periodic sync disabled (sync_interval <= 0 or not set)")
    
    def get_core_model(self, model_name: str):
        """Get core model class by name (DI helper)."""
        return self.models.get(model_name)
    
    def get_session(self):
        """Get database session context manager."""
        return self.db_session_maker()
    
    def get_yandex_device_id(self, device: Any) -> Optional[str]:
        """
        Helper: получить Yandex device ID из Device или PluginBinding.
        Используется для удобного доступа к данным Яндекса из ядра.
        """
        if hasattr(device, 'meta') and device.meta:
            return device.meta.get('yandex_device_id')
        return None
    
    def get_yandex_device_data(self, device: Any) -> Optional[Dict[str, Any]]:
        """
        Helper: получить полные данные устройства Яндекса из Device.meta.
        Используется для удобного доступа к данным Яндекса из ядра.
        """
        if hasattr(device, 'meta') and device.meta:
            return device.meta.get('yandex_device')
        return None
    
    def is_yandex_device(self, device: Any) -> bool:
        """
        Helper: проверить, является ли устройство устройством Яндекса.
        """
        if hasattr(device, 'meta') and device.meta:
            return device.meta.get('external_source') == 'yandex'
        return False

    async def _get_current_user_id(self, request: Request) -> str:
        """
        Extract user_id from request state or raise 401.
        Без зависимостей от ядра - использует только DI и request.state.
        """
        # Option 1: User already set by middleware/dependency
        if hasattr(request.state, 'user') and request.state.user:
            user = request.state.user
            # Handle both User object and dict payload
            if hasattr(user, 'id'):
                return str(user.id)
            elif isinstance(user, dict):
                user_id = user.get('sub') or user.get('id')
                if user_id:
                    return str(user_id)
            else:
                return str(user)
        
        # Option 2: Try to use get_current_user_fn if available (DI from core)
        # This function is injected by plugin_loader and handles both Bearer token and cookies
        if hasattr(self, 'get_current_user_fn') and self.get_current_user_fn:
            try:
                # get_current_user_fn expects request and optional credentials
                # We need to call it without Depends, so we create a mock credentials object
                from fastapi.security import HTTPAuthorizationCredentials
                
                # Try with Bearer token first
                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header.split(" ")[1]
                    # Create mock credentials object
                    class MockCredentials:
                        def __init__(self, token):
                            self.credentials = token
                    
                    try:
                        # Try to call with credentials
                        user = await self.get_current_user_fn(request, MockCredentials(token))
                        if user:
                            return str(user.id if hasattr(user, 'id') else user)
                    except Exception:
                        # If that fails, try without credentials (it will check cookies)
                        pass
                
                # Fallback: try without credentials (will check cookies)
                try:
                    user = await self.get_current_user_fn(request)
                    if user:
                        return str(user.id if hasattr(user, 'id') else user)
                except Exception as e:
                    self.logger.debug(f"get_current_user_fn failed: {e}")
            except Exception as e:
                self.logger.debug(f"Failed to use get_current_user_fn: {e}")
        
        # Option 3: Try to extract user_id from token payload directly (if middleware set it)
        # This is a fallback - middleware should set request.state.user, but sometimes
        # it might set just the payload in a different format
        try:
            # Check if there's a token payload in request state (set by middleware)
            if hasattr(request.state, 'token_payload'):
                payload = request.state.token_payload
                if isinstance(payload, dict):
                    user_id = payload.get('sub') or payload.get('id')
                    if user_id:
                        return str(user_id)
        except Exception:
            pass
        
        # No user found - raise 401
        raise HTTPException(status_code=401, detail="Unauthorized: user authentication required")
        

    # ========== Device sync methods (delegates to handlers) ==========
    
    async def sync_devices(self, payload: Dict[str, Any] = None):
        """
        Public method для синхронизации устройств.
        Вызывается из routes/devices.py
        Делегирует выполнение в device_handlers.
        """
        user_id = payload.get('user_id') if payload else None
        return await self.device_handlers.sync_devices(payload, user_id=user_id)
    
    async def sync_device_states(self, payload: Dict[str, Any] = None):
        """
        Public method для синхронизации состояний устройств.
        Делегирует выполнение в device_handlers.
        """
        user_id = payload.get('user_id') if payload else None
        return await self.device_handlers.sync_device_states(user_id=user_id)

    async def _save_account(self, user_id: str, ya_user_id: Optional[str], access_token: str, refresh_token: Optional[str], expires_in: Optional[int]):
        """
        Helper to persist Yandex account info. Delegates to service.save_account.
        """
        try:
            await save_account(user_id=user_id, ya_user_id=ya_user_id, access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)
            self.logger.info(f"✅ Saved Yandex account for user {user_id}")
        except Exception as e:
            self.logger.error(f"❌ Failed to save Yandex account for user {user_id}: {e}", exc_info=True)
            raise
    
    async def _handle_device_execute_event(self, event_name: str, data: Dict[str, Any]):
        """
        Обработчик событий выполнения действий на устройствах.
        Вызывается когда event_bus публикует событие device.{device_id}.execute
        """
        self.logger.info(f"📢 Event handler called: event={event_name}")
        self.logger.info(f"   Data: {data}")
        
        try:
            device_id = data.get('device_id')
            plugin = data.get('plugin')
            payload = data.get('payload', {})
            
            self.logger.info(f"   Device ID: {device_id}")
            self.logger.info(f"   Plugin: {plugin}")
            self.logger.info(f"   Payload: {payload}")
            
            # Проверяем, что это событие для нашего плагина
            if plugin != 'yandex_smart_home':
                self.logger.debug(f"❌ Event not for yandex_smart_home plugin: {plugin}")
                return
            
            self.logger.info(f"✅ Event is for yandex_smart_home plugin")
            
            # Получаем модели через DI
            PluginBinding = self.models.get('PluginBinding')
            if not PluginBinding:
                self.logger.error("❌ PluginBinding model not available")
                return
            
            # Получаем привязку устройства
            async with self.get_session() as db:
                binding_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.device_id == device_id,
                        PluginBinding.plugin_name == 'yandex_smart_home',
                        PluginBinding.enabled == True
                    )
                )
                binding = binding_result.scalar_one_or_none()
                
                if not binding or not binding.selector:
                    self.logger.warning(f"❌ No binding found for device {device_id}")
                    return
                
                self.logger.info(f"✅ Found binding: selector={binding.selector}")
                
                # Получаем user_id из binding config или из payload
                user_id = payload.get('user_id')
                if not user_id and binding.config:
                    user_id = binding.config.get('user_id')
                
                self.logger.info(f"👤 User ID: {user_id}")
                
                if not user_id:
                    self.logger.warning(f"❌ No user_id found for device {device_id}")
                    self.logger.warning(f"   Binding config: {binding.config}")
                    self.logger.warning(f"   Payload: {payload}")
                    return
                
                account_result = await db.execute(
                    select(YandexUser).where(YandexUser.user_id == user_id)
                )
                account = account_result.scalar_one_or_none()
                
                if not account or not account.access_token:
                    self.logger.warning(f"❌ No access token found for user {user_id}")
                    return
                
                self.logger.info(f"✅ Got access token for user {user_id}")
                
                # Извлекаем action из event_name или payload
                action = payload.get('action', 'execute')
                if '.' in event_name:
                    action = event_name.split('.')[-1]  # Последняя часть event_name (execute, turn_on, etc.)
                
                self.logger.info(f"🎯 Action: {action}")
                
                params = payload.get('params', payload)
                self.logger.info(f"📦 Params: {params}")
                
                # Отправляем команду в Яндекс API через device_manager
                yandex_device_id = binding.selector
                
                # Вызываем метод device_manager для выполнения действия
                await self.device_manager.execute_device_action(
                    yandex_device_id=yandex_device_id,
                    action=action,
                    params=params,
                    access_token=account.access_token,
                    device_id=device_id
                )
                
                self.logger.info(f"✅ Command completed successfully")
                
        except Exception as e:
            self.logger.error(f"❌ Error handling device execute event: {e}", exc_info=True)
    
    async def _get_device_full_data(self, access_token: str, yandex_device_id: str) -> Dict[str, Any]:
        """
        Получить полные данные устройства из Яндекс Smart Home API (с last_updated).
        Использует GET /v1.0/devices/{device_id}.
        
        Returns:
            Dict с полными данными устройства включая capabilities с last_updated
        """
        self.logger.info(f"🔍 Getting full device data for: {yandex_device_id}")
        
        try:
            api_base = cfg_get('YANDEX_API_BASE', self.config, default='https://api.iot.yandex.net')
            device_path = f'/v1.0/devices/{yandex_device_id}'
            
            parsed_api = http.client.urlsplit(api_base)
            conn_class = http.client.HTTPSConnection if parsed_api.scheme == 'https' else http.client.HTTPConnection
            conn = conn_class(parsed_api.hostname, parsed_api.port or (443 if parsed_api.scheme == 'https' else 80), timeout=10)
            
            try:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                conn.request('GET', device_path, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                text = data.decode('utf-8') if data else ''
                
                if not (200 <= resp.status < 300):
                    self.logger.warning(f'⚠️ Failed to get full device data: {resp.status}')
                    return {}
                
                device_data = json.loads(text) if text else {}
                self.logger.info(f"✅ Got full device data with last_updated timestamps")
                return device_data
                
            finally:
                try:
                    conn.close()
                except:
                    pass
        except Exception as e:
            self.logger.error(f"❌ Error getting full device data: {e}", exc_info=True)
            return {}
    
    async def _periodic_sync_all_users(self):
        """
        Периодическая синхронизация устройств для всех пользователей с привязанными аккаунтами Яндекса.
        Вызывается автоматически через TaskManager.
        """
        try:
            from .models import YandexUser
            from sqlalchemy import select
            
            # Уменьшаем логирование - только один раз при старте
            if not hasattr(self, '_periodic_sync_started'):
                self.logger.info("🔄 Starting periodic sync for all users")
                self._periodic_sync_started = True
            else:
                self.logger.debug("🔄 Periodic sync running")
            
            # Получаем всех пользователей с привязанными аккаунтами Яндекса
            async with self.get_session() as db:
                users_result = await db.execute(select(YandexUser))
                yandex_users = users_result.scalars().all()
            
            if not yandex_users:
                self.logger.debug("No Yandex users found for periodic sync")
                return
            
            synced_count = 0
            error_count = 0
            
            for yandex_user in yandex_users:
                try:
                    user_id = yandex_user.user_id
                    self.logger.debug(f"Syncing devices for user {user_id}")
                    
                    # Выполняем синхронизацию для пользователя
                    await self.sync_devices({'user_id': user_id})
                    await self.sync_device_states({'user_id': user_id})
                    
                    # Опционально: полная синхронизация (может быть медленной)
                    if self.config.get('full_sync_on_periodic', False):
                        if hasattr(self, 'device_manager') and self.device_manager:
                            await self.device_manager.poll_authoritative_states(
                                user_id=user_id,
                                concurrency=5,  # Меньше параллелизма для фоновой задачи
                                delay_between=0.05
                            )
                    
                    synced_count += 1
                    self.logger.debug(f"✅ Synced devices for user {user_id}")
                    
                except Exception as e:
                    error_count += 1
                    self.logger.warning(f"⚠️ Failed to sync devices for user {yandex_user.user_id}: {e}")
            
            self.logger.info(f"🔄 Periodic sync completed: {synced_count} users synced, {error_count} errors")
            
        except Exception as e:
            self.logger.error(f"❌ Error in periodic sync: {e}", exc_info=True)
    
    async def on_unload(self):
        """Cleanup при выгрузке."""
        # Останавливаем все фоновые задачи
        if hasattr(self, 'tasks'):
            self.tasks.stop_all()
        self.logger.info("👋 Yandex Smart Home plugin with auth integration unloaded")