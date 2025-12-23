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
        "/docs", 
        "/redoc",
        "/"
    ]
    
    # Check if the route requires authentication
    if any(request.url.path.startswith(route) for route in public_routes):
        response = await call_next(request)
        return response
    
    # For protected routes, check authentication
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        # Allow requests without auth for certain routes (like plugin endpoints that have their own auth)
        response = await call_next(request)
        return response
    
    token = auth_header.split(" ")[1]
    payload = verify_token(token)
    
    if payload is None:
        # Don't block the request but add user info if valid
        response = await call_next(request)
        return response
    
    # Add user info to request state
    request.state.user = payload
    
    response = await call_next(request)
    return response