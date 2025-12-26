"""Yandex Smart Home API client."""
import asyncio
import json
import logging
import http.client
import os
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import urljoin, urlsplit

from .utils import cfg_get

logger = logging.getLogger(__name__)


class YandexAPIClient:
    """Client for Yandex Smart Home API."""

    def __init__(self, config: dict | None = None):
        """Initialize API client."""
        self.config = config or {}
        self.api_base = cfg_get('YANDEX_API_BASE', self.config, default='https://api.iot.yandex.net')

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get full user info including devices, groups, and scenarios.
        Uses GET /v1.0/user/info
        """
        logger.info("🔍 Getting user info from Yandex API")
        return await self._make_request('GET', '/v1.0/user/info', access_token)

    async def get_devices(self, access_token: str) -> Dict[str, Any]:
        """Get list of devices.

        Yandex exposes devices under `/v1.0/user/info` (which includes rooms,
        groups and devices). Use that endpoint directly to avoid 404 errors.
        
        For individual device data, use get_device(access_token, device_id) 
        which calls GET /v1.0/devices/{device_id}
        """
        # Используем /v1.0/user/info напрямую, так как /v1.0/user/devices возвращает 404
        full = await self._make_request('GET', '/v1.0/user/info', access_token)
        if isinstance(full, dict) and 'devices' in full:
            return {'devices': full.get('devices', [])}
        return {'devices': []}

    async def get_device(self, access_token: str, device_id: str) -> Dict[str, Any]:
        """Get full device data with capabilities. Uses GET /v1.0/devices/{device_id}"""
        logger.info(f"🔍 Getting device data for: {device_id}")
        return await self._make_request('GET', f'/v1.0/devices/{device_id}', access_token)

    async def send_action(self, access_token: str, device_id: str, action_type: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send action to device.
        Uses POST /v1.0/devices/actions
        """
        logger.info(f"🚀 Sending action to device {device_id}: {action_type}")
        
        payload = {
            "devices": [{
                "id": device_id,
                "actions": [{
                    "type": action_type,
                    "state": state
                }]
            }]
        }
        
        return await self._make_request('POST', '/v1.0/devices/actions', access_token, payload)

    async def _make_request(self, method: str, path: str, access_token: str, payload: Dict[str, Any] | None = None, max_retries: int = 3, retry_delay: float = 1.0) -> Dict[str, Any]:
        """
        Make HTTP request to Yandex API with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path
            access_token: Yandex access token
            payload: Optional request payload
            max_retries: Maximum number of retry attempts for transient errors
            retry_delay: Delay between retries in seconds
        """
        import asyncio
        
        last_exception = None
        for attempt in range(max_retries):
            try:
                # build full URL and parse it correctly
                full_url = urljoin(self.api_base, path)
                parsed = urlsplit(full_url)

                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                req_path = parsed.path or '/'
                if parsed.query:
                    req_path = f"{req_path}?{parsed.query}"

                logger.debug(f"🔗 Yandex API request -> {method.upper()} {full_url} (host={host}, port={port}, path={req_path})")

                conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
                conn = conn_class(host, port, timeout=10)

                try:
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    }

                    body = None
                    if payload:
                        body = json.dumps(payload).encode('utf-8')

                    conn.request(method.upper(), req_path, body=body, headers=headers)
                    resp = conn.getresponse()
                    data = resp.read()
                    text = data.decode('utf-8') if data else ''

                    logger.debug(f"📥 Yandex API response: status={resp.status}")

                    # Persist certain Yandex responses to file for debugging/inspection
                    try:
                        # Only save successful responses for user info/devices endpoints
                        if resp.status == 200 and any(p in req_path for p in ('/v1.0/user/info', '/v1.0/devices')):
                            # plugin root: two dirs up from this file
                            plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                            data_dir = os.path.join(plugin_root, 'data')
                            os.makedirs(data_dir, exist_ok=True)

                            # safe filename from path
                            name = req_path.strip('/').replace('/', '_').replace('?', '_') or 'response'
                            timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
                            latest_path = os.path.join(data_dir, f"latest_{name}.json")
                            ts_path = os.path.join(data_dir, f"{name}_{timestamp}.json")

                            try:
                                with open(latest_path, 'w', encoding='utf-8') as f:
                                    f.write(text or '')
                                with open(ts_path, 'w', encoding='utf-8') as f:
                                    f.write(text or '')
                                logger.debug(f"💾 Saved Yandex response to {latest_path} and {ts_path}")
                            except Exception as wf:
                                logger.warning(f"Failed to write Yandex response to file: {wf}")
                    except Exception:
                        logger.debug('Failed to persist Yandex response', exc_info=True)

                    if not (200 <= resp.status < 300):
                        # Retry on 5xx errors (server errors) and 429 (rate limit)
                        if resp.status >= 500 or resp.status == 429:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                                logger.warning(f'⚠️ Yandex API error {resp.status}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})')
                                await asyncio.sleep(wait_time)
                                last_exception = Exception(f'Yandex API error: {resp.status} {text}')
                                continue
                        logger.error(f'❌ Yandex API error: {resp.status} {text}')
                        return {}

                    return json.loads(text) if text else {}
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            except Exception as e:
                # Retry on network errors
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f'⚠️ Network error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries}): {e}')
                    await asyncio.sleep(wait_time)
                    last_exception = e
                    continue
                last_exception = e
        
        # All retries exhausted
        logger.error(f"❌ Error making request to Yandex API after {max_retries} attempts: {last_exception}", exc_info=True)
        return {}
