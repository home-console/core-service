"""Device state management for Yandex Smart Home."""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)


class DeviceStateManager:
    """Manager for device state tracking and updates."""

    def __init__(self, db_session_maker, parse_last_updated_func, logger=None, device_model=None, online_timeout=None):
        """Initialize state manager.
        
        Args:
            db_session_maker: Database session maker
            parse_last_updated_func: Function to parse last_updated timestamps
            logger: Logger instance
            device_model: Device model class
            online_timeout: Time in seconds after which device is considered offline (default: 300)
        """
        self.db_session_maker = db_session_maker
        self.parse_last_updated = parse_last_updated_func
        self.logger = logger or logging.getLogger(__name__)
        self.device_model = device_model  # Device model passed via DI
        self.online_timeout = online_timeout or 300  # По умолчанию 5 минут

    async def update_device_status(self, device_id: str, yandex_device_data: Dict[str, Any]):
        """
        Update device status (is_online, is_on, last_seen) from Yandex data.
        """
        if not self.device_model:
            self.logger.warning("Device model not available, skipping status update")
            return
            
        try:
            Device = self.device_model
            
            # Determine if device is online and get on/off state
            last_updated = None
            is_online = False
            last_seen = None
            
            # Find last_updated in capabilities
            capabilities = yandex_device_data.get('capabilities', [])
            if capabilities:
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
                    if lu:
                        if last_updated is None:
                            last_updated = lu
                        else:
                            dt_new = self.parse_last_updated(lu)
                            dt_old = self.parse_last_updated(last_updated)
                            if dt_new and dt_old:
                                if dt_new > dt_old:
                                    last_updated = lu
                            else:
                                try:
                                    if isinstance(lu, (int, float)) and isinstance(last_updated, (int, float)):
                                        if lu > last_updated:
                                            last_updated = lu
                                    elif str(lu) > str(last_updated):
                                        last_updated = lu
                                except Exception:
                                    last_updated = lu

            # Уменьшаем логирование - только для отладки
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Capability timestamps raw: {[(cap.get('last_updated') if isinstance(cap, dict) else None) for cap in capabilities]}")

            if last_updated:
                parsed = self.parse_last_updated(last_updated)
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"Parsed last_updated raw='{last_updated}' -> parsed='{parsed}'")
                if parsed:
                    last_seen = parsed
                    # Устройство считается онлайн, если последнее обновление было менее online_timeout секунд назад
                    is_online = (datetime.utcnow() - last_seen).total_seconds() < self.online_timeout
                else:
                    # Если не удалось распарсить, но есть last_updated, считаем устройство онлайн
                    # (возможно это новый формат timestamp)
                    is_online = True
                    last_seen = datetime.utcnow()
            
            # Determine on/off state
            is_on = False
            for cap in capabilities:
                if cap.get('type') == 'devices.capabilities.on_off':
                    state = cap.get('state', {})
                    is_on = state.get('value', False)
                    break
            
            # Update device in database
            async with self.db_session_maker() as db:
                result = await db.execute(select(Device).where(Device.id == device_id))
                device = result.scalar_one_or_none()
                if device:
                    device.is_online = is_online
                    device.is_on = is_on
                    device.last_seen = last_seen
                    await db.commit()
                    
                    # Уменьшаем логирование - только для отладки или важных изменений
                    if self.logger.isEnabledFor(logging.DEBUG) or is_online:
                        self.logger.debug(f"✅ Updated device status: online={is_online}, on={is_on}, last_seen={last_seen}")
        except Exception as e:
            self.logger.error(f"❌ Error updating device status: {e}", exc_info=True)

    async def get_device_state(self, access_token: str, yandex_device_id: str, api_client) -> Dict[str, Any]:
        """
        Get current device state from Yandex API.
        """
        self.logger.info(f"🔍 Getting device state for: {yandex_device_id}")
        
        try:
            device_data = await api_client.get_device(access_token, yandex_device_id)
            if not device_data:
                return {}
            
            self.logger.info(f"📄 Device data: {device_data}")
            
            # Extract state from capabilities
            state = {}
            capabilities = device_data.get('capabilities', [])
            for cap in capabilities:
                cap_state = cap.get('state', {})
                instance = cap_state.get('instance')
                value = cap_state.get('value')
                
                if instance == 'on':
                    state['on'] = value
                elif instance == 'brightness':
                    state['brightness'] = value
                elif instance == 'temperature':
                    state['temperature'] = value
                elif instance == 'color':
                    state['color'] = value
            
            self.logger.info(f"✅ Extracted state: {state}")
            return state
        except Exception as e:
            self.logger.error(f"❌ Error getting device state: {e}", exc_info=True)
            return {}
