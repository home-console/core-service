"""
Auth Service Integration Module.

Provides integration with authentication service for secure token management.
This module allows plugins to securely store and retrieve tokens through
the central auth service.
"""
import os
import http.client
import json
from typing import Dict, Any, Optional
from urllib.parse import urljoin


# Configuration
AUTH_SERVICE_BASE = os.getenv('AUTH_SERVICE_BASE', 'http://auth-service:8000')
INTERNAL_TOKEN = os.getenv('INTERNAL_SERVICE_TOKEN', 'internal-service-token')


class AuthClient:
    """Client for interacting with the auth service."""
    
    @staticmethod
    def call_auth_service(endpoint: str, method: str = 'GET', data: Dict[str, Any] = None,
                         headers: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Call auth service endpoint.
        
        Args:
            endpoint: API endpoint (e.g. /api/tokens/cloud/yandex)
            method: HTTP method
            data: Data for POST/PUT requests
            headers: Additional headers
            
        Returns:
            Response from auth service
        """
        url = urljoin(AUTH_SERVICE_BASE, endpoint)
        parsed = http.client.urlsplit(url)
        
        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)
        
        try:
            req_headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
            if headers:
                req_headers.update(headers)
            
            if data:
                req_headers["Content-Type"] = "application/json"
                body = json.dumps(data).encode('utf-8')
            else:
                body = None
            
            conn.request(method.upper(), parsed.path, body=body, headers=req_headers)
            resp = conn.getresponse()
            response_data = resp.read()
            text = response_data.decode('utf-8') if response_data else ''
            
            if not (200 <= resp.status < 300):
                raise Exception(f'Auth service returned {resp.status}: {text}')
            
            return json.loads(text) if text else {}
            
        finally:
            try:
                conn.close()
            except:
                pass


class TokenManager:
    """Manager for secure token storage and retrieval."""
    
    @staticmethod
    def store_cloud_token(service: str, token: str, refresh_token: str = None) -> bool:
        """
        Store cloud service token in auth service.
        
        Args:
            service: Service identifier (e.g. 'yandex_smart_home')
            token: Access token
            refresh_token: Refresh token (optional)
            
        Returns:
            Success status
        """
        try:
            data = {
                "service": service,
                "token": token
            }
            if refresh_token:
                data["refresh_token"] = refresh_token
            
            result = AuthClient.call_auth_service(
                f'/api/tokens/cloud/{service}',
                'POST',
                data
            )
            return True
        except Exception as e:
            print(f"Failed to store token for {service}: {e}")
            return False
    
    @staticmethod
    def get_cloud_token(service: str) -> Optional[str]:
        """
        Retrieve cloud service token from auth service.
        
        Args:
            service: Service identifier (e.g. 'yandex_smart_home')
            
        Returns:
            Token string or None if not found
        """
        try:
            tokens = AuthClient.call_auth_service('/api/tokens/cloud')
            service_token = tokens.get(service)
            
            if not service_token:
                return None
                
            # Token can be a string or an object
            return service_token if isinstance(service_token, str) else service_token.get('token')
        except Exception as e:
            print(f"Failed to get token for {service}: {e}")
            return None
    
    @staticmethod
    def delete_cloud_token(service: str) -> bool:
        """
        Delete cloud service token from auth service.
        
        Args:
            service: Service identifier
            
        Returns:
            Success status
        """
        try:
            AuthClient.call_auth_service(
                f'/api/tokens/cloud/{service}',
                'DELETE'
            )
            return True
        except Exception as e:
            print(f"Failed to delete token for {service}: {e}")
            return False


# Convenience functions for common services
def store_yandex_token(access_token: str, refresh_token: str = None) -> bool:
    """Store Yandex Smart Home token."""
    return TokenManager.store_cloud_token('yandex_smart_home', access_token, refresh_token)


def get_yandex_token() -> Optional[str]:
    """Get Yandex Smart Home token."""
    return TokenManager.get_cloud_token('yandex_smart_home')


def delete_yandex_token() -> bool:
    """Delete Yandex Smart Home token."""
    return TokenManager.delete_cloud_token('yandex_smart_home')


def store_google_token(access_token: str, refresh_token: str = None) -> bool:
    """Store Google Assistant token."""
    return TokenManager.store_cloud_token('google_assistant', access_token, refresh_token)


def get_google_token() -> Optional[str]:
    """Get Google Assistant token."""
    return TokenManager.get_cloud_token('google_assistant')


def store_amazon_token(access_token: str, refresh_token: str = None) -> bool:
    """Store Amazon Alexa token."""
    return TokenManager.store_cloud_token('amazon_alexa', access_token, refresh_token)


def get_amazon_token() -> Optional[str]:
    """Get Amazon Alexa token."""
    return TokenManager.get_cloud_token('amazon_alexa')