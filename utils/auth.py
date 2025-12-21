"""
Authentication and JWT utilities.
"""
import os
import json
import time
import base64
import hmac
import hashlib
import uuid
from typing import Dict, Optional


def generate_jwt_token(
    subject: str,
    audience: str = "client_manager",
    issuer: str = "core_service",
    expires_in: int = 120
) -> str:
    """
    Generate a JWT token for admin authentication.
    
    Supports both HS256 (shared secret) and RS256 (private key) algorithms.
    Configuration via environment variables:
    - ADMIN_JWT_SECRET: Shared secret for HS256
    - ADMIN_JWT_ALG: Algorithm (HS256 or RS256), defaults to HS256
    - ADMIN_JWT_PRIVATE_KEY or ADMIN_JWT_PRIVATE_KEY_FILE: Private key for RS256
    
    Args:
        subject: JWT subject (sub claim)
        audience: JWT audience (aud claim)
        issuer: JWT issuer (iss claim)
        expires_in: Token expiration time in seconds
        
    Returns:
        JWT token string
        
    Raises:
        ValueError: If no authentication secret is configured
    """
    admin_jwt_secret = os.getenv('ADMIN_JWT_SECRET', '')
    if not admin_jwt_secret:
        raise ValueError("ADMIN_JWT_SECRET not configured")
    
    alg = os.getenv('ADMIN_JWT_ALG', 'HS256').upper()
    
    # Try PyJWT for RS256/HS256 handling
    try:
        import jwt as _pyjwt
    except ImportError:
        _pyjwt = None
    
    if alg == 'RS256' and _pyjwt:
        # Read private key from env or file
        priv = os.getenv('ADMIN_JWT_PRIVATE_KEY')
        if not priv:
            priv_file = os.getenv('ADMIN_JWT_PRIVATE_KEY_FILE')
            if priv_file:
                try:
                    with open(priv_file, 'r') as f:
                        priv = f.read()
                except Exception:
                    priv = None
        
        if not priv:
            # Fallback to HS256 if no private key provided
            alg = 'HS256'
        else:
            jwt_payload = {
                'iss': issuer,
                'sub': subject,
                'aud': audience,
                'iat': int(time.time()),
                'exp': int(time.time()) + expires_in,
                'jti': str(uuid.uuid4())
            }
            return _pyjwt.encode(jwt_payload, priv, algorithm='RS256')
    
    # HS256 implementation (shared secret)
    def _b64u(data: bytes) -> str:
        """Base64 URL-safe encoding without padding."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode('utf-8')
    
    header = {'alg': 'HS256', 'typ': 'JWT'}
    jwt_claims = {
        'iss': issuer,
        'sub': subject,
        'aud': audience,
        'iat': int(time.time()),
        'exp': int(time.time()) + expires_in,
        'jti': str(uuid.uuid4())
    }
    
    header_b = _b64u(json.dumps(header).encode('utf-8'))
    payload_b = _b64u(json.dumps(jwt_claims).encode('utf-8'))
    signing = (header_b + '.' + payload_b).encode('utf-8')
    sig = hmac.new(admin_jwt_secret.encode('utf-8'), signing, hashlib.sha256).digest()
    sig_b = _b64u(sig)
    
    return header_b + '.' + payload_b + '.' + sig_b


def get_admin_headers() -> Dict[str, str]:
    """
    Get admin authentication headers for internal API calls.
    
    Supports:
    - JWT token generation (ADMIN_JWT_SECRET)
    - Simple bearer token (ADMIN_TOKEN)
    
    Returns:
        Dictionary with Authorization header
    """
    # Try JWT first
    admin_jwt_secret = os.getenv('ADMIN_JWT_SECRET', '')
    if admin_jwt_secret:
        try:
            token = generate_jwt_token(subject='admin')
            return {'Authorization': f'Bearer {token}'}
        except Exception:
            pass
    
    # Fallback to ADMIN_TOKEN
    admin_token = os.getenv('ADMIN_TOKEN', '')
    if admin_token:
        return {'Authorization': f'Bearer {admin_token}'}
    
    return {}


def require_admin_auth() -> Dict[str, str]:
    """
    Get admin headers, raising an exception if no auth is configured.
    
    Returns:
        Dictionary with Authorization header
        
    Raises:
        ValueError: If no admin authentication is configured
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")
    admin_jwt_secret = os.getenv("ADMIN_JWT_SECRET", "")
    admin_jwt_alg = os.getenv('ADMIN_JWT_ALG', '').upper()
    admin_jwt_priv = os.getenv('ADMIN_JWT_PRIVATE_KEY') or os.getenv('ADMIN_JWT_PRIVATE_KEY_FILE')
    
    if not admin_token and not admin_jwt_secret and not (admin_jwt_alg == 'RS256' and admin_jwt_priv):
        raise ValueError("Server ADMIN_TOKEN, ADMIN_JWT_SECRET, or RS256 private key not configured")
    
    return get_admin_headers()
