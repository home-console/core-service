"""
Redis cache utilities for performance optimization.
Provides caching layer for frequently accessed data.
"""
import os
import json
import logging
from typing import Any, Optional, Dict
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)

# Глобальный Redis клиент
_redis_client: Optional[Any] = None
_cache_enabled = True


def _get_redis_client():
    """Получить или создать Redis клиент."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            _redis_client = redis.from_url(redis_url, decode_responses=True)
            logger.info("✅ Redis cache client initialized")
        except ImportError:
            logger.warning("⚠️ redis package not installed, caching disabled")
            _cache_enabled = False
            return None
        except Exception as e:
            logger.warning(f"⚠️ Failed to connect to Redis: {e}, caching disabled")
            _cache_enabled = False
            return None
    return _redis_client


async def cache_get(key: str, default: Any = None) -> Any:
    """
    Получить значение из кэша.
    
    Args:
        key: Ключ кэша
        default: Значение по умолчанию если ключ не найден
        
    Returns:
        Значение из кэша или default
    """
    if not _cache_enabled:
        return default
    
    try:
        client = _get_redis_client()
        if client is None:
            return default
        
        value = await client.get(key)
        if value is None:
            return default
        
        # Пытаемся распарсить JSON
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    except Exception as e:
        logger.debug(f"Cache get error for key {key}: {e}")
        return default


async def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    """
    Сохранить значение в кэш.
    
    Args:
        key: Ключ кэша
        value: Значение для сохранения
        ttl: Time to live в секундах (по умолчанию 5 минут)
        
    Returns:
        True если успешно сохранено
    """
    if not _cache_enabled:
        return False
    
    try:
        client = _get_redis_client()
        if client is None:
            return False
        
        # Сериализуем значение в JSON
        if isinstance(value, (dict, list)):
            serialized = json.dumps(value)
        else:
            serialized = str(value)
        
        await client.setex(key, ttl, serialized)
        return True
    except Exception as e:
        logger.debug(f"Cache set error for key {key}: {e}")
        return False


async def cache_delete(key: str) -> bool:
    """
    Удалить значение из кэша.
    
    Args:
        key: Ключ кэша
        
    Returns:
        True если успешно удалено
    """
    if not _cache_enabled:
        return False
    
    try:
        client = _get_redis_client()
        if client is None:
            return False
        
        await client.delete(key)
        return True
    except Exception as e:
        logger.debug(f"Cache delete error for key {key}: {e}")
        return False


async def cache_delete_pattern(pattern: str) -> int:
    """
    Удалить все ключи по паттерну.
    
    Args:
        pattern: Паттерн ключей (например, "devices:*")
        
    Returns:
        Количество удаленных ключей
    """
    if not _cache_enabled:
        return 0
    
    try:
        client = _get_redis_client()
        if client is None:
            return 0
        
        keys = []
        async for key in client.scan_iter(match=pattern):
            keys.append(key)
        
        if keys:
            await client.delete(*keys)
        
        return len(keys)
    except Exception as e:
        logger.debug(f"Cache delete pattern error for pattern {pattern}: {e}")
        return 0


def cached(ttl: int = 300, key_prefix: str = ""):
    """
    Декоратор для кэширования результатов async функций.
    
    Args:
        ttl: Time to live в секундах
        key_prefix: Префикс для ключа кэша
        
    Пример:
        @cached(ttl=600, key_prefix="devices")
        async def get_devices():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Генерируем ключ кэша
            cache_key_parts = [key_prefix, func.__name__]
            if args:
                cache_key_parts.extend([str(arg) for arg in args])
            if kwargs:
                cache_key_parts.extend([f"{k}:{v}" for k, v in sorted(kwargs.items())])
            cache_key = ":".join(filter(None, cache_key_parts))
            
            # Пытаемся получить из кэша
            cached_value = await cache_get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache HIT for {cache_key}")
                return cached_value
            
            # Выполняем функцию
            logger.debug(f"Cache MISS for {cache_key}")
            result = await func(*args, **kwargs)
            
            # Сохраняем в кэш
            await cache_set(cache_key, result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator


async def close_cache():
    """Закрыть соединение с Redis."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            _redis_client = None
            logger.info("✅ Redis cache client closed")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")

