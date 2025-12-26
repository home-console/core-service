"""Device management for Yandex Smart Home."""
import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..api.utils import cfg_get

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manager for Yandex device discovery, sync, and commands."""

    def __init__(self, db_session_maker, api_client, state_manager, config=None, models: dict | None = None):
        """Initialize device manager."""
        self.db_session_maker = db_session_maker
        self.api_client = api_client
        self.state_manager = state_manager
        self.config = config or {}
        # models is a dict of core models provided via DI from plugin
        self.models = models or {}
        self.logger = logging.getLogger(__name__)

    async def discover_devices_for_user(self, user_id: str, access_token: str) -> int:
        """
        Discover and create devices for user after account linking.
        Uses GET /v1.0/user/info to get full smart home info.
        """
        # Get models from plugin's core_models (DI)
        try:
            from ..main import YandexSmartHomePlugin
            # Models will be accessed via plugin instance if available
        except:
            pass
        
        try:
            # Get full smart home info
            user_info_data = await self.api_client.get_user_info(access_token)
            
            yandex_devices = user_info_data.get('devices', []) if isinstance(user_info_data, dict) else []
            yandex_groups = user_info_data.get('groups', []) if isinstance(user_info_data, dict) else []
            yandex_scenarios = user_info_data.get('scenarios', []) if isinstance(user_info_data, dict) else []
            
            self.logger.info(f"Parsed from /v1.0/user/info: {len(yandex_devices)} devices, {len(yandex_groups)} groups, {len(yandex_scenarios)} scenarios")

            if not yandex_devices:
                self.logger.info(f"No devices found for user {user_id}")
                await self._save_user_info(user_id, user_info_data)
                return 0

            discovered_count = 0
            async with self.db_session_maker() as db:
                # Save full info
                from ..models import YandexUser
                res = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
                account = res.scalar_one_or_none()
                if account:
                    if not account.config:
                        account.config = {}
                    account.config.update({
                        'user_info': {
                            'devices': yandex_devices,
                            'groups': yandex_groups,
                            'scenarios': yandex_scenarios,
                            'synced_at': datetime.utcnow().isoformat()
                        }
                    })
                    await db.commit()

                # Process devices
                for yandex_dev in yandex_devices:
                    yandex_dev_id = yandex_dev.get('id')
                    if not yandex_dev_id:
                        continue

                    # Check if binding already exists
                    binding_result = await db.execute(
                        select(PluginBinding).where(
                            PluginBinding.plugin_name == 'yandex_smart_home',
                            PluginBinding.selector == yandex_dev_id
                        )
                    )
                    existing_binding = binding_result.scalar_one_or_none()

                    if not existing_binding:
                        # New device - create binding and internal device
                        last_updated = None
                        is_online = False
                        is_on = False
                        
                        capabilities = yandex_dev.get('capabilities', [])
                        if capabilities:
                            # Find most recent last_updated
                            from ..api.utils import parse_last_updated
                            
                            for cap in capabilities:
                                lu = None
                                for key in ('last_updated', 'lastUpdated', 'updated_at', 'timestamp', 'time'):
                                    v = cap.get(key) if isinstance(cap, dict) else None
                                    if v:
                                        lu = v
                                        break
                                if not lu and isinstance(cap.get('state'), dict):
                                    for key in ('last_updated', 'lastUpdated', 'updated_at', 'timestamp', 'time'):
                                        v = cap['state'].get(key)
                                        if v:
                                            lu = v
                                            break
                                if lu and (last_updated is None or (isinstance(lu, (int, float)) and isinstance(last_updated, (int, float)) and lu > last_updated) or (isinstance(lu, str) and (last_updated is None or str(lu) > str(last_updated)))):
                                    last_updated = lu

                            if last_updated:
                                last_seen_dt = parse_last_updated(last_updated)
                                if last_seen_dt:
                                    is_online = (datetime.utcnow() - last_seen_dt).total_seconds() < 300
                                    last_seen_value = last_seen_dt
                                else:
                                    last_seen_value = None
                            else:
                                last_seen_value = None

                            # Check on_off capability
                            for cap in capabilities:
                                if cap.get('type') == 'devices.capabilities.on_off':
                                    state = cap.get('state', {})
                                    is_on = state.get('value', False)
                                    break
                        
                        device = Device(
                            id=str(uuid4()),
                            name=yandex_dev.get('name', f"Yandex Device {yandex_dev_id}"),
                            type=yandex_dev.get('type', 'unknown'),
                            is_online=is_online,
                            is_on=is_on,
                            last_seen=last_seen_value if last_updated else None,
                            meta={
                                'yandex_device_id': yandex_dev_id,
                                'yandex_device': yandex_dev,
                                'auto_created': True,
                                'user_id': user_id,
                                'capabilities': yandex_dev.get('capabilities', []),
                                'properties': yandex_dev.get('properties', [])
                            }
                        )
                        db.add(device)
                        await db.flush()

                        binding = PluginBinding(
                            id=str(uuid4()),
                            device_id=device.id,
                            plugin_name='yandex_smart_home',
                            selector=yandex_dev_id,
                            enabled=True,
                            config={
                                'yandex_device': yandex_dev,
                                'auto_mapped': True,
                                'user_id': user_id,
                                'capabilities': yandex_dev.get('capabilities', []),
                                'properties': yandex_dev.get('properties', [])
                            }
                        )
                        db.add(binding)
                        await db.commit()

                        discovered_count += 1
                        self.logger.info(f"Discovered new Yandex device: {device.name} (ID: {yandex_dev_id}, online={is_online}, on={is_on})")

            # Save groups and scenarios info
            await self._save_user_info(user_id, user_info_data)

            return discovered_count
        except Exception as e:
            self.logger.error(f"Error discovering devices for user {user_id}: {e}", exc_info=True)
            return 0

    async def _save_user_info(self, user_id: str, user_info_data: dict):
        """Save full smart home info (devices, groups, scenarios) to database."""
        from ..models import YandexUser
        
        try:
            async with self.db_session_maker() as db:
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
                    self.logger.info(f"Saved user info for user {user_id}")
        except Exception as e:
            self.logger.warning(f"Failed to save user info for user {user_id}: {e}")

    async def send_command(self, access_token: str, yandex_device_id: str, action: str, params: Dict[str, Any]):
        """
        Send command to Yandex device.
        """
        self.logger.info(f"🚀 Sending command: device={yandex_device_id}, action={action}, params={params}")
        
        try:
            # Map action to Yandex type and params
            action_type = self._map_action_to_yandex_type(action, params)
            yandex_params = self._convert_action_to_yandex_params(action, params)
            
            self.logger.info(f"🔧 Action type: {action_type}")
            self.logger.info(f"🔧 Converted params: {yandex_params}")
            
            # Build state object
            state_obj = self._build_state_object(action_type, yandex_params)
            
            # Send to API
            return await self.api_client.send_action(access_token, yandex_device_id, action_type, state_obj)
        except Exception as e:
            self.logger.error(f"❌ Error sending command: {e}", exc_info=True)
            raise

    def _convert_action_to_yandex_params(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convert internal action to Yandex API params."""
        payload = {}
        
        if action == 'turn_on' or action == 'on':
            payload['on'] = True
        elif action == 'turn_off' or action == 'off':
            payload['on'] = False
        elif action == 'toggle':
            payload['on'] = params.get('on', True)
        elif action == 'set_brightness' or 'brightness' in params:
            payload['brightness'] = params.get('brightness', 50)
        elif action == 'set_color' or 'color' in params:
            payload['rgb'] = params.get('color', params.get('rgb', 'FFFFFF'))
        elif action == 'set_temperature' or 'temperature' in params:
            payload['temperature'] = params.get('temperature', 4000)
        else:
            payload = {k: v for k, v in params.items() if not k.startswith('_')}
        
        return payload if payload else {}

    def _map_action_to_yandex_type(self, action: str, params: Dict[str, Any]) -> str:
        """Map action to Yandex Smart Home API type."""
        if action in ('turn_on', 'on', 'turn_off', 'off', 'toggle'):
            return 'devices.capabilities.on_off'
        elif action == 'set_brightness' or 'brightness' in params:
            return 'devices.capabilities.range'
        elif action == 'set_color' or 'color' in params:
            return 'devices.capabilities.color_setting'
        elif action == 'set_temperature' or 'temperature' in params:
            return 'devices.capabilities.mode'
        else:
            return 'devices.capabilities.on_off'

    def _build_state_object(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Build state object for Yandex API."""
        if action_type == 'devices.capabilities.on_off':
            return {
                "instance": "on",
                "value": params.get('on', False)
            }
        elif action_type == 'devices.capabilities.range':
            return {
                "instance": "brightness",
                "value": params.get('brightness', 50)
            }
        elif action_type == 'devices.capabilities.color_setting':
            return {
                "instance": "rgb",
                "value": params.get('rgb', 'FFFFFF')
            }
        elif action_type == 'devices.capabilities.mode':
            return {
                "instance": "temperature",
                "value": params.get('temperature', 4000)
            }
        else:
            return params

    async def execute_device_action(
        self,
        yandex_device_id: str,
        action: str,
        params: Dict[str, Any],
        access_token: str,
        device_id: str = None
    ):
        """
        Execute action on Yandex device.
        
        Args:
            yandex_device_id: Yandex device ID
            action: Action to execute (turn_on, turn_off, toggle, etc.)
            params: Action parameters
            access_token: Yandex access token
            device_id: Internal device ID (optional, for logging)
        """
        try:
            self.logger.info(f"🚀 Executing action '{action}' on Yandex device {yandex_device_id}")
            
            # Для toggle нужно сначала получить текущее состояние
            if action == 'toggle':
                self.logger.info(f"🔄 Toggle action - getting current state first")
                device_data = await self.api_client.get_device(access_token, yandex_device_id)
                # Извлекаем текущее состояние on_off из capabilities
                current_on = False
                for cap in device_data.get('capabilities', []):
                    if cap.get('type') == 'devices.capabilities.on_off':
                        current_on = cap.get('state', {}).get('value', False)
                        break
                params['on'] = not current_on
                self.logger.info(f"🔄 Toggle: current={current_on} → new={not current_on}")
            
            # Конвертируем action в параметры Yandex API
            yandex_params = self._convert_action_to_yandex_params(action, params)
            self.logger.info(f"🔧 Converted params: {yandex_params}")
            
            # Определяем тип capability
            yandex_action_type = self._map_action_to_yandex_type(action, yandex_params)
            self.logger.info(f"🔧 Action type: {yandex_action_type}")
            
            # Строим state объект
            state_obj = self._build_state_object(yandex_action_type, yandex_params)
            
            # Отправляем команду
            result = await self.api_client.send_action(
                access_token=access_token,
                device_id=yandex_device_id,
                action_type=yandex_action_type,
                state=state_obj
            )
            
            self.logger.info(f"✅ Command completed: {result}")
            
            # Обновляем состояние устройства из Яндекса
            if device_id:
                try:
                    device_data = await self.api_client.get_device(access_token, yandex_device_id)
                    if device_data:
                        await self.state_manager.update_device_status(device_id, device_data)
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to update device status: {e}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error executing action: {e}", exc_info=True)
            raise

    async def poll_authoritative_states(self, user_id: Optional[str] = None, concurrency: int = 5, delay_between: float = 0.05) -> int:
        """
        Poll /v1.0/devices/{device_id} for authoritative `state` (online/offline) per device.

        - user_id: limit to bindings associated with this user (if binding.config.user_id present)
        - concurrency: how many parallel requests to Yandex
        - delay_between: small delay between starting tasks to avoid tight bursts

        Returns number of devices successfully updated.
        """
        try:
            # Lazy import core models and plugin YandexUser model
            # Use models provided via DI (from plugin) instead of importing core directly
            PluginBinding = None
            Device = None
            if isinstance(self.models, dict):
                PluginBinding = self.models.get('PluginBinding')
                Device = self.models.get('Device')

            from ..models import YandexUser

            # Find access token for user
            access_token = None
            if user_id:
                async with self.db_session_maker() as db:
                    res = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
                    ya = res.scalar_one_or_none()
                    if ya:
                        access_token = ya.access_token

            if not access_token:
                self.logger.warning(f"No access_token found for user {user_id}; skipping authoritative poll")
                return 0

            # Collect bindings
            async with self.db_session_maker() as db:
                if PluginBinding is None:
                    # fallback: query by table name direct SQL (not implemented)
                    self.logger.error("PluginBinding model not importable; cannot poll authoritative states")
                    return 0

                res = await db.execute(select(PluginBinding).where(PluginBinding.plugin_name == 'yandex_smart_home'))
                bindings = res.scalars().all()

            # Filter by user_id in binding.config if provided
            target_bindings = []
            for b in bindings:
                try:
                    cfg = b.config or {}
                    if user_id and cfg.get('user_id') and str(cfg.get('user_id')) != str(user_id):
                        continue
                    if not b.selector:
                        continue
                    target_bindings.append(b)
                except Exception:
                    continue

            if not target_bindings:
                self.logger.info("No Yandex bindings found for authoritative polling")
                return 0

            sem = asyncio.Semaphore(concurrency)

            updated = 0

            async def _poll_binding(binding):
                nonlocal updated
                async with sem:
                    try:
                        # small spacing to avoid immediate bursts
                        if delay_between:
                            await asyncio.sleep(delay_between)

                        yandex_id = binding.selector
                        device_data = await self.api_client.get_device(access_token, yandex_id)
                        if not device_data:
                            self.logger.debug(f"No device data for {yandex_id}")
                            return

                        # Let state_manager update computed fields first
                        try:
                            await self.state_manager.update_device_status(binding.device_id, device_data)
                        except Exception as e:
                            self.logger.warning(f"state_manager failed for {yandex_id}: {e}")

                        # If API returns authoritative 'state' field, use it to set is_online
                        state_flag = device_data.get('state')
                        if state_flag in ('online', 'offline') and Device is not None:
                            is_online = True if state_flag == 'online' else False
                            try:
                                async with self.db_session_maker() as db:
                                    res = await db.execute(select(Device).where(Device.id == binding.device_id))
                                    dev = res.scalar_one_or_none()
                                    if dev:
                                        dev.is_online = is_online
                                        await db.commit()
                                        updated += 1
                            except Exception as e:
                                self.logger.warning(f"Failed to persist authoritative state for {yandex_id}: {e}")
                    except Exception as e:
                        self.logger.debug(f"Poll failed for binding {getattr(binding, 'id', None)}: {e}", exc_info=True)

            tasks = [asyncio.create_task(_poll_binding(b)) for b in target_bindings]
            if tasks:
                await asyncio.gather(*tasks)

            self.logger.info(f"Authoritative poll completed: updated={updated} devices")
            return updated
        except Exception as e:
            self.logger.error(f"Error polling authoritative states: {e}", exc_info=True)
            return 0
