"""
Yandex Smart Home - API Client.
Functions for communicating with Yandex Smart Home API.
"""
import http.client
import json
import logging
from typing import Dict, Any, Optional

from .auth import cfg_get

logger = logging.getLogger(__name__)


class YandexApiClient:
    """Client for Yandex Smart Home API."""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.api_base = cfg_get('YANDEX_API_BASE', self.config, default='https://api.iot.yandex.net')
        self.logger = logging.getLogger(__name__)
    
    def _get_connection(self):
        """Get HTTP connection to Yandex API."""
        parsed = http.client.urlsplit(self.api_base)
        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        return conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get user info with all devices.
        Uses GET /v1.0/user/info
        """
        self.logger.info("🔍 Getting user info from Yandex API")
        
        try:
            conn = self._get_connection()
            try:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                conn.request('GET', '/v1.0/user/info', headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                text = data.decode('utf-8') if data else ''
                
                if not (200 <= resp.status < 300):
                    self.logger.warning(f'⚠️ Failed to get user info: {resp.status}')
                    return {}
                
                return json.loads(text) if text else {}
            finally:
                try:
                    conn.close()
                except:
                    pass
        except Exception as e:
            self.logger.error(f"❌ Error getting user info: {e}", exc_info=True)
            return {}
    
    async def get_device_state(self, access_token: str, device_id: str) -> Dict[str, Any]:
        """
        Get current device state.
        Uses GET /v1.0/devices/{device_id}
        
        Returns:
            Dict with current state, e.g., {'on': True, 'brightness': 75}
        """
        self.logger.info(f"🔍 Getting device state for: {device_id}")
        
        try:
            conn = self._get_connection()
            device_path = f'/v1.0/devices/{device_id}'
            
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
                    self.logger.warning(f'⚠️ Failed to get device state: {resp.status}')
                    return {}
                
                device_data = json.loads(text) if text else {}
                
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
                
                return state
                
            finally:
                try:
                    conn.close()
                except:
                    pass
        except Exception as e:
            self.logger.error(f"❌ Error getting device state: {e}", exc_info=True)
            return {}
    
    async def get_device_full_data(self, access_token: str, device_id: str) -> Dict[str, Any]:
        """
        Get full device data including last_updated timestamps.
        Uses GET /v1.0/devices/{device_id}
        """
        self.logger.info(f"🔍 Getting full device data for: {device_id}")
        
        try:
            conn = self._get_connection()
            device_path = f'/v1.0/devices/{device_id}'
            
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
                
                return json.loads(text) if text else {}
                
            finally:
                try:
                    conn.close()
                except:
                    pass
        except Exception as e:
            self.logger.error(f"❌ Error getting full device data: {e}", exc_info=True)
            return {}
    
    async def send_command(self, access_token: str, device_id: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send command to Yandex Smart Home device.
        Uses POST /v1.0/devices/actions
        """
        self.logger.info(f"🔵 Sending command: device={device_id}, action={action}, params={params}")
        
        try:
            conn = self._get_connection()
            actions_path = '/v1.0/devices/actions'
            
            try:
                # Map action to Yandex type
                yandex_action_type = self._map_action_to_yandex_type(action, params)
                yandex_params = self._convert_action_to_yandex_params(action, params)
                
                # Build state object with instance and value
                state_obj = self._build_state_object(yandex_action_type, yandex_params)
                
                yandex_payload = {
                    "devices": [{
                        "id": device_id,
                        "actions": [{
                            "type": yandex_action_type,
                            "state": state_obj
                        }]
                    }]
                }
                
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                body = json.dumps(yandex_payload)
                
                self.logger.info(f"📤 Sending to Yandex API: {body}")
                
                conn.request('POST', actions_path, body=body.encode('utf-8'), headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                text = data.decode('utf-8') if data else ''
                
                self.logger.info(f"📥 Yandex API response: status={resp.status}")
                
                if not (200 <= resp.status < 300):
                    self.logger.error(f'❌ Yandex API error: {resp.status} {text}')
                    raise Exception(f'Yandex action error: {resp.status} {text}')
                
                return json.loads(text) if text else {}
                
            finally:
                try:
                    conn.close()
                except:
                    pass
        except Exception as e:
            self.logger.error(f"❌ Error sending command to Yandex: {e}", exc_info=True)
            raise
    
    def _build_state_object(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Build state object for Yandex API request."""
        if action_type == 'devices.capabilities.on_off':
            return {"instance": "on", "value": params.get('on', False)}
        elif action_type == 'devices.capabilities.range':
            return {"instance": "brightness", "value": params.get('brightness', 50)}
        elif action_type == 'devices.capabilities.color_setting':
            return {"instance": "rgb", "value": params.get('rgb', 'FFFFFF')}
        elif action_type == 'devices.capabilities.mode':
            return {"instance": "temperature", "value": params.get('temperature', 4000)}
        else:
            return params
    
    def _convert_action_to_yandex_params(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert internal action to Yandex API parameters.
        """
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
        """
        Map actions to Yandex Smart Home API types.
        """
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
