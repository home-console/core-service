"""
Yandex Smart Home - Authentication and OAuth.
"""
import os
import http.client
import json
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin, urlencode

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Configuration
AUTH_SERVICE_BASE = os.getenv('AUTH_SERVICE_BASE', 'http://auth-service:8000')
INTERNAL_TOKEN = os.getenv('INTERNAL_SERVICE_TOKEN', 'internal-service-token')


def cfg_get(env_key: str, config: dict, cfg_key: str | None = None, default: str | None = None) -> str:
    """
    Read value from config (lowercase key or exact), 
    else from environment, else default.
    """
    if not config:
        return os.getenv(env_key, default or "")

    key = cfg_key or env_key.lower()
    if key in config and config[key]:
        return config[key]
    if env_key in config and config[env_key]:
        return config[env_key]

    return os.getenv(env_key, default or "")


class AuthServiceClient:
    """Client for interacting with authorization service."""

    @staticmethod
    def call_auth_service(endpoint: str, method: str = 'GET', data: Dict[str, Any] = None,
                         headers: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Call authorization service API.

        Args:
            endpoint: API endpoint (e.g., /api/tokens/cloud/yandex)
            method: HTTP method
            data: Data for POST/PUT requests
            headers: Additional headers

        Returns:
            Response from authorization service
        """
        url = urljoin(AUTH_SERVICE_BASE, endpoint)
        parsed = http.client.urlsplit(url)

        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

        try:
            req_headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
            if headers:
                req_headers.update(headers)


                body = json.dumps(data).encode('utf-8')
            else:
                body = None

            conn.request(method.upper(), parsed.path, body=body, headers=req_headers)
            resp = conn.getresponse()
            response_data = resp.read()
            text = response_data.decode('utf-8') if response_data else ''

            if not (200 <= resp.status < 300):
                raise HTTPException(
                    status_code=resp.status,
                    detail=f'Auth service error: {resp.status} {text}'
                )

            return json.loads(text) if text else {}

        finally:
            try:
                conn.close()
            except:
                pass


class YandexAuthManager:
    """Yandex OAuth Authorization Manager."""

    @staticmethod
    def get_yandex_oauth_url(state: str = None, config: dict | None = None) -> str:
        """
        Get URL for Yandex OAuth authorization.

        Args:
            state: State for CSRF protection

        Returns:
            URL to redirect user to
        """
        logger.info(f"🔍 get_yandex_oauth_url called with config = {config}")
        client_id = cfg_get('YANDEX_CLIENT_ID', config)
        redirect_uri = cfg_get('YANDEX_REDIRECT_URI', config)
        scope = cfg_get('YANDEX_OAUTH_SCOPE', config, 'yandex_oauth_scope', '')
        logger.info(f"🔍 Resolved: client_id={client_id}, redirect_uri={redirect_uri}, scope={scope or '(empty)'}")

        if not client_id or not redirect_uri:
            raise HTTPException(
                status_code=500,
                detail='YANDEX_CLIENT_ID and YANDEX_REDIRECT_URI must be set'
            )

        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
        }
        if scope and scope.strip():
            params['scope'] = scope.strip()
        if state:
            params['state'] = state

        authorize_url = cfg_get('YANDEX_OAUTH_AUTHORIZE', config, default='https://oauth.yandex.ru/authorize')
        return authorize_url + '?' + urlencode(params)

    @staticmethod
    async def exchange_code_for_token(code: str, config: dict | None = None) -> Dict[str, Any]:
        """
        Exchange authorization code for token.

        Args:
            code: Authorization code from Yandex

        Returns:
            Token information
        """
        client_id = cfg_get('YANDEX_CLIENT_ID', config)
        client_secret = cfg_get('YANDEX_CLIENT_SECRET', config)
        redirect_uri = cfg_get('YANDEX_REDIRECT_URI', config)

        if not all([client_id, client_secret, redirect_uri]):
            raise HTTPException(
                status_code=500,
                detail='YANDEX_CLIENT_ID, SECRET and REDIRECT_URI must be set'
            )

        token_url = cfg_get('YANDEX_OAUTH_TOKEN', config, default='https://oauth.yandex.ru/token')
        body = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri
        }

        parsed = http.client.urlsplit(token_url)
        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            conn.request('POST', parsed.path, body=urlencode(body), headers=headers)
            resp = conn.getresponse()
            response_data = resp.read()
            text = response_data.decode('utf-8') if response_data else ''

            if not (200 <= resp.status < 300):
                raise HTTPException(
                    status_code=502,
                    detail=f'Failed exchanging token: {resp.status} {text}'
                )

            return json.loads(text)

        finally:
            try:
                conn.close()
            except:
                pass

    @staticmethod
    async def save_yandex_tokens(access_token: str, refresh_token: str = None, config: dict | None = None) -> bool:
        """
        Save Yandex tokens to authorization system.

        Args:
            access_token: Access token from Yandex
            refresh_token: Refresh token from Yandex (optional)

        Returns:
            Success status
        """
        # Legacy method - uses direct HTTP calls, no external dependencies needed
        try:
                data = {
                    "service": 'yandex_smart_home',
                    "token": access_token,
                    "refresh_token": refresh_token
                }

                auth_base = cfg_get('AUTH_SERVICE_BASE', config, default=AUTH_SERVICE_BASE)
                url = urljoin(auth_base, '/api/tokens/cloud/yandex_smart_home')
                parsed = http.client.urlsplit(url)

                conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
                conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

                try:
                    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}", "Content-Type": "application/json"}
                    body = json.dumps(data).encode('utf-8')

                    conn.request('POST', parsed.path, body=body, headers=headers)
                    resp = conn.getresponse()
                    response_data = resp.read()
                    text = response_data.decode('utf-8') if response_data else ''

                    if not (200 <= resp.status < 300):
                        raise Exception(f'Auth service returned {resp.status}: {text}')

                    return True

                finally:
                    try:
                        conn.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Failed to save Yandex tokens: {e}")
                return False

    @staticmethod
    async def get_yandex_token() -> Optional[str]:
        """
        Get Yandex token from authorization system.

        Returns:
            Yandex token or None if not configured
        """
        # Legacy method - uses direct HTTP calls
        try:
                url = urljoin(AUTH_SERVICE_BASE, '/api/tokens/cloud')
                parsed = http.client.urlsplit(url)

                conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
                conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

                try:
                    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
                    conn.request('GET', parsed.path, headers=headers)
                    resp = conn.getresponse()
                    response_data = resp.read()
                    text = response_data.decode('utf-8') if response_data else ''

                    if resp.status != 200:
                        raise Exception(f'Failed to fetch tokens: {resp.status} {text}')

                    tokens = json.loads(text) if text else {}
                    ytoken = tokens.get('yandex_smart_home')

                    if not ytoken:
                        return None

                    return ytoken if isinstance(ytoken, str) else ytoken.get('token')

                finally:
                    try:
                        conn.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Failed to get Yandex token: {e}")
                return None
