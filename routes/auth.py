"""
Authentication endpoints for Home Console.
Provides login, logout, token management and user session management.
"""
import os
import jwt
from jwt import exceptions as jwt_exceptions
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import get_session
from ..models import User, Plugin, PluginVersion
from ..utils.auth import verify_password, hash_password


logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None
    expires_in: int


# Yandex OAuth Configuration
YANDEX_OAUTH_AUTHORIZE = os.getenv('YANDEX_OAUTH_AUTHORIZE', 'https://oauth.yandex.ru/authorize')
YANDEX_OAUTH_TOKEN = os.getenv('YANDEX_OAUTH_TOKEN', 'https://oauth.yandex.ru/token')
YANDEX_API_BASE = os.getenv('YANDEX_API_BASE', 'https://api.iot.yandex.net')
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
YANDEX_REDIRECT_URI = os.getenv('YANDEX_REDIRECT_URI', 'http://localhost:3000/api/auth/yandex/callback')


@router.get("/auth/yandex/login")
async def yandex_oauth_login():
    """Start Yandex OAuth flow."""
    if not YANDEX_CLIENT_ID or not YANDEX_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail='YANDEX_CLIENT_ID and YANDEX_REDIRECT_URI must be set for Yandex OAuth'
        )

    # Generate state parameter for CSRF protection
    import secrets
    state = secrets.token_urlsafe(32)

    # Store state in session or database for verification later
    # For simplicity, we'll use URL parameter (in production use secure storage)

    params = {
        'response_type': 'code',
        'client_id': YANDEX_CLIENT_ID,
        'redirect_uri': YANDEX_REDIRECT_URI,
        'scope': 'iot',
        'state': state
    }

    from urllib.parse import urlencode
    auth_url = YANDEX_OAUTH_AUTHORIZE + '?' + urlencode(params)
    return {"auth_url": auth_url}


@router.get("/auth/yandex/callback")
async def yandex_oauth_callback(request: Request):
    """Handle Yandex OAuth callback."""
    code = request.query_params.get('code')
    state = request.query_params.get('state')

    if not code:
        raise HTTPException(status_code=400, detail='Missing code parameter')

    # Verify state parameter (implement proper validation in production)
    # For now, just check if present

    # Exchange code for token
    token_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': YANDEX_CLIENT_ID,
        'client_secret': YANDEX_CLIENT_SECRET,
        'redirect_uri': YANDEX_REDIRECT_URI
    }

    parsed = http.client.urlsplit(YANDEX_OAUTH_TOKEN)
    conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
    conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        conn.request('POST', parsed.path, body=urlencode(token_data), headers=headers)
        resp = conn.getresponse()
        response_data = resp.read()
        text = response_data.decode('utf-8') if response_data else ''

        if resp.status != 200:
            raise HTTPException(status_code=502, detail=f'Failed exchanging token: {resp.status} {text}')

        token_resp = json.loads(text)
        access_token = token_resp.get('access_token')

        if not access_token:
            raise HTTPException(status_code=502, detail='No access_token in token response')

        # Get user info from Yandex
        user_info = await get_yandex_user_info(access_token)

        # Create or update user in our system
        user = await create_or_update_yandex_user(user_info, token_resp)

        # Create JWT tokens for our system
        access_token_data = {
            "sub": user.id,
            "username": user.username,
            "email": user.email,
            "role": getattr(user, 'role', 'user'),
            "source": "yandex_oauth"
        }
        access_token = create_access_token(access_token_data)
        refresh_token = create_refresh_token({"sub": user.id})

        # Update last login time
        async with get_session() as db:
            user.last_login = datetime.utcnow()
            await db.commit()

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            refresh_token=refresh_token,
            expires_in=60 * 24 * 60  # 24 hours in seconds
        )

    finally:
        try:
            conn.close()
        except:
            pass


async def get_yandex_user_info(access_token: str) -> Dict[str, Any]:
    """Get user info from Yandex using access token."""
    # Yandex OAuth doesn't have a standard userinfo endpoint
    # Instead, we'll use Yandex Profile API or get user info through other means
    # For IoT Smart Home, we'll get devices and extract user info from there
    # Alternative: use https://login.yandex.ru/info endpoint

    headers = {"Authorization": f"OAuth {access_token}"}
    url = "https://login.yandex.ru/info"

    parsed = http.client.urlsplit(url)
    conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
    conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

    try:
        conn.request('GET', parsed.path, headers=headers)
        resp = conn.getresponse()
        response_data = resp.read()
        text = response_data.decode('utf-8') if response_data else ''

        if resp.status != 200:
            raise HTTPException(status_code=502, detail=f'Failed getting user info: {resp.status} {text}')

        user_info = json.loads(text)
        return user_info

    finally:
        try:
            conn.close()
        except:
            pass


async def create_or_update_yandex_user(yandex_user_info: Dict[str, Any], token_data: Dict[str, Any]) -> User:
    """Create or update user based on Yandex OAuth data."""
    async with get_session() as db:
        # Try to find user by Yandex ID or email
        yandex_id = yandex_user_info.get('id')
        email = yandex_user_info.get('default_email') or yandex_user_info.get('emails', [None])[0]
        username = yandex_user_info.get('display_name') or yandex_user_info.get('real_name') or f"yandex_user_{yandex_id}"

        # First, try to find by Yandex ID (stored in metadata)
        existing_user = None
        if yandex_id:
            # Search for user with this Yandex ID in metadata
            result = await db.execute(select(User))
            all_users = result.scalars().all()
            for user in all_users:
                if user.metadata and user.metadata.get('yandex_id') == yandex_id:
                    existing_user = user
                    break

        # If not found by Yandex ID, try to find by email
        if not existing_user and email:
            result = await db.execute(select(User).where(User.email == email))
            existing_user = result.scalar_one_or_none()

        if existing_user:
            # Update existing user
            existing_user.username = username
            existing_user.email = email or existing_user.email
            existing_user.last_login = datetime.utcnow()

            # Update metadata with Yandex info
            if not existing_user.metadata:
                existing_user.metadata = {}
            existing_user.metadata.update({
                'yandex_id': yandex_id,
                'yandex_display_name': yandex_user_info.get('display_name'),
                'yandex_real_name': yandex_user_info.get('real_name'),
                'yandex_scope': token_data.get('scope'),
                'yandex_token_issued': datetime.utcnow().isoformat()
            })

            user = existing_user
        else:
            # Create new user
            user_id = str(uuid.uuid4())

            # Create user with Yandex data
            user = User(
                id=user_id,
                username=username,
                email=email or f"{user_id}@yandex.home.console",
                password_hash="",  # No password for OAuth users
                role="user",
                enabled=True,
                created_at=datetime.utcnow(),
                last_login=datetime.utcnow(),
                metadata={
                    'yandex_id': yandex_id,
                    'yandex_display_name': yandex_user_info.get('display_name'),
                    'yandex_real_name': yandex_user_info.get('real_name'),
                    'yandex_scope': token_data.get('scope'),
                    'yandex_token_issued': datetime.utcnow().isoformat(),
                    'oauth_provider': 'yandex'
                }
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)

        # Now sync Yandex devices to our system
        await sync_yandex_devices(user.id, token_data['access_token'])

        return user


async def sync_yandex_devices(user_id: str, access_token: str):
    """Sync Yandex Smart Home devices to our system."""
    try:
        # Get devices from Yandex Smart Home API
        headers = {"Authorization": f"Bearer {access_token}"}
        devices_url = f"{YANDEX_API_BASE}/v1.0/user/devices"

        parsed = http.client.urlsplit(devices_url)
        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

        try:
            conn.request('GET', parsed.path, headers=headers)
            resp = conn.getresponse()
            response_data = resp.read()
            text = response_data.decode('utf-8') if response_data else ''

            if resp.status != 200:
                logger.warning(f"Failed to get devices from Yandex: {resp.status} {text}")
                return

            devices_data = json.loads(text) if text else {}
            devices = devices_data.get('devices', [])

            # Import Device model and PluginBinding to sync devices
            from ..models import Device, PluginBinding
            from sqlalchemy import select

            async with get_session() as db:
                for device in devices:
                    device_id = device.get('id')
                    device_name = device.get('name', f"Yandex Device {device_id}")
                    device_type = device.get('type', 'devices.types.other')
                    device_info = device.get('device_info', {})

                    # Check if device already exists
                    existing_device = await db.execute(
                        select(Device).where(
                            Device.external_id == device_id,
                            Device.external_source == 'yandex'
                        )
                    )
                    existing_device = existing_device.scalar_one_or_none()

                    if existing_device:
                        # Update existing device
                        existing_device.name = device_name
                        existing_device.type = device_type
                        existing_device.config = {
                            'yandex_data': device,
                            'last_sync': datetime.utcnow().isoformat()
                        }
                    else:
                        # Create new device
                        new_device = Device(
                            id=f"yandex_{device_id}",
                            name=device_name,
                            type=device_type,
                            external_id=device_id,
                            external_source='yandex',
                            config={
                                'yandex_data': device,
                                'last_sync': datetime.utcnow().isoformat()
                            }
                        )
                        db.add(new_device)

                        # Create binding to associate with user
                        binding = PluginBinding(
                            device_id=new_device.id,
                            plugin_name='yandex_smart_home',
                            selector=device_id,  # The Yandex device ID
                            enabled=True,
                            config={
                                'user_id': user_id,
                                'yandex_device_data': device
                            }
                        )
                        db.add(binding)

                await db.commit()
                logger.info(f"Synced {len(devices)} Yandex devices for user {user_id}")

        finally:
            try:
                conn.close()
            except:
                pass

    except Exception as e:
        logger.error(f"Error syncing Yandex devices: {e}")


# Secret key for JWT (should come from environment)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "home_console_default_secret")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = 7  # 7 days


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict):
    """Create JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify JWT token and return payload."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt_exceptions.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt_exceptions.PyJWTError as e:
        logger.error(f"Token verification error: {e}")
        return None


async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current authenticated user from token."""
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("access_token")
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    
    async with get_session() as db:
        user = await db.execute(select(User).where(User.id == user_id))
        user = user.scalar_one_or_none()
        
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
    
    return user


def _set_access_cookie(response: Response, access_token: str):
    secure_cookie = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    same_site = os.getenv("COOKIE_SAMESITE", "lax").lower()
    if same_site not in ("lax", "strict", "none"):
        same_site = "lax"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure_cookie,
        samesite=same_site,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(login_request: LoginRequest, response: Response):
    """Login endpoint - authenticates user and returns JWT tokens."""
    username = login_request.username
    password = login_request.password
    
    async with get_session() as db:
        # Find user by username
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect username or password")
        
        # Create access token
        access_token_data = {
            "sub": user.id,
            "username": user.username,
            "role": getattr(user, 'role', 'user')  # default role
        }
        access_token = create_access_token(access_token_data)
        
        # Create refresh token
        refresh_token = create_refresh_token({"sub": user.id})
        
        # Update last login time
        user.last_login = datetime.utcnow()
        await db.commit()
        
        # Set HttpOnly cookie for access token
        _set_access_cookie(response, access_token)
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )


@router.post("/auth/register")
async def register(register_request: RegisterRequest):
    """Register new user."""
    username = register_request.username
    password = register_request.password
    email = register_request.email
    
    # Hash password
    password_hash = hash_password(password)
    
    async with get_session() as db:
        # Check if user already exists
        existing_user = await db.execute(select(User).where(User.username == username))
        if existing_user.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already registered")
        
        # Check if email already exists
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Create new user
        from uuid import uuid4
        user_id = str(uuid4())
        
        user = User(
            id=user_id,
            username=username,
            email=email,
            password_hash=password_hash,
            created_at=datetime.utcnow(),
            last_login=None
        )
        
        db.add(user)
        try:
            await db.commit()
            return {"status": "success", "message": "User registered successfully"}
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/auth/refresh")
async def refresh_token(request: Request):
    """Refresh access token using refresh token."""
    # In a real implementation, refresh tokens would be stored in a database
    # For now, we'll just issue a new access token based on the refresh token
    # But in practice, refresh tokens should be stored and validated
    
    # This is a simplified implementation - in production, refresh tokens should be stored
    # in a database with proper invalidation mechanisms
    raise HTTPException(status_code=501, detail="Refresh token endpoint not implemented yet")


@router.post("/auth/logout")
async def logout(response: Response):
    """Logout endpoint - clears access token cookie."""
    response.delete_cookie("access_token", path="/")
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/auth/me")
async def get_user_profile(current_user = Depends(get_current_user)):
    """Get current user profile."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None
    }


@router.get("/auth/verify")
async def verify_auth(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify authentication token."""
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("access_token")
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return {"valid": True, "user_id": payload.get("sub"), "username": payload.get("username")}


# Middleware to check authentication for protected routes
async def auth_middleware(request: Request, call_next):
    """Middleware to check authentication for protected routes."""
    # Define public routes that don't require authentication
    public_routes = [
        "/api/auth/login",
        "/api/auth/register", 
        "/api/auth/refresh",
        "/api/docs", 
        "/api/redoc",
        "/api/openapi.json",
        "/docs",  # Legacy support
        "/redoc",  # Legacy support
        "/"
    ]
    
    # Check if the route requires authentication
    if any(request.url.path.startswith(route) for route in public_routes):
        response = await call_next(request)
        return response
    
    # For protected routes, check authentication
    # Try Bearer token first, then fallback to cookie
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    elif not token:
        # Fallback to cookie
        token = request.cookies.get("access_token")
    
    if token:
        payload = verify_token(token)
        if payload:
            # Add user info to request state
            request.state.user = payload
    else:
        # No token found - allow request to continue (plugin endpoints handle their own auth)
        pass
    
    response = await call_next(request)
    return response