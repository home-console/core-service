"""
Authentication utilities for Home Console.
Provides password hashing, JWT token creation and validation functions.
"""
import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext


# Initialize password context for hashing.
# bcrypt_sha256 позволяет не упираться в 72-байтовый лимит исходного bcrypt
# (Passlib сначала хеширует SHA-256, затем bcrypt), что избегает ValueError.
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def verify_password_hash(password: str, password_hash: str) -> bool:
    """Verify password against hash (alias for verify_password)."""
    return verify_password(password, password_hash)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    # Secret key for JWT (should come from environment)
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "home_console_default_secret")
    JWT_ALGORITHM = "HS256"
    
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Default expiration: 24 hours
        ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict):
    """Create JWT refresh token."""
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "home_console_default_secret")
    JWT_ALGORITHM = "HS256"
    
    REFRESH_TOKEN_EXPIRE_DAYS = 7  # 7 days
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify JWT token and return payload."""
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "home_console_default_secret")
    JWT_ALGORITHM = "HS256"
    
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None


def get_password_hash(password: str) -> str:
    """Get hash for a password (alias for hash_password)."""
    return hash_password(password)


def generate_jwt_token(
    subject: str = "admin",
    expires_delta: Optional[timedelta] = None,
    permissions: Optional[list[str]] = None,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Унифицированная генерация JWT для внутренних запросов.
    
    - Если задан ADMIN_TOKEN, предпочтём его (но вернём как Bearer).
    - По умолчанию HS256 с ключом из ADMIN_JWT_SECRET или JWT_SECRET_KEY.
    - Можно добавить произвольные claims через extra.
    """
    # Static token fallback (used only in get_admin_headers)
    admin_token = os.getenv("ADMIN_TOKEN")
    if admin_token:
        return admin_token
    
    secret = (
        os.getenv("ADMIN_JWT_SECRET")
        or os.getenv("JWT_SECRET_KEY")
        or "home_console_default_secret"
    )
    alg = os.getenv("ADMIN_JWT_ALG", "HS256").upper()
    
    # Support PEM key passed via env ADMIN_JWT_PRIVATE_KEY / _FILE (optional)
    key_from_env = os.getenv("ADMIN_JWT_PRIVATE_KEY")
    if not key_from_env:
        key_file = os.getenv("ADMIN_JWT_PRIVATE_KEY_FILE")
        if key_file and os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as fh:
                key_from_env = fh.read()
    if key_from_env:
        secret = key_from_env

    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(hours=24))

    payload: Dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": expire,
    }

    if issuer or os.getenv("JWT_ISSUER"):
        payload["iss"] = issuer or os.getenv("JWT_ISSUER")
    if audience or os.getenv("JWT_AUDIENCE"):
        payload["aud"] = audience or os.getenv("JWT_AUDIENCE")
    if permissions:
        payload["permissions"] = permissions
    if extra:
        payload.update(extra)

    return jwt.encode(payload, secret, algorithm=alg)


def get_admin_headers() -> Dict[str, str]:
    """
    Возвращает заголовки для внутренних запросов:
    - Если ADMIN_TOKEN задан, используем его.
    - Иначе генерируем JWT через generate_jwt_token().
    """
    token = os.getenv("ADMIN_TOKEN")
    if not token:
        token = generate_jwt_token()
    return {"Authorization": f"Bearer {token}"}