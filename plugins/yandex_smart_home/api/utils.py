"""Utility functions for Yandex Smart Home plugin."""
import os
from datetime import datetime, timezone


def cfg_get(env_key: str, config, cfg_key: str | None = None, default: str | None = None) -> str:
    """
    Читаем значение из config (dict или PluginConfig из SDK),
    иначе берём из окружения, иначе default.
    
    Args:
        env_key: Ключ переменной окружения (например: YANDEX_CLIENT_ID)
        config: dict или PluginConfig экземпляр
        cfg_key: Альтернативный ключ для config (если не указан, используется env_key.lower())
        default: Значение по умолчанию
    """
    if not config:
        return os.getenv(env_key, default or "")

    key = cfg_key or env_key.lower()
    
    # Проверяем тип config - это может быть dict или PluginConfig из SDK
    # PluginConfig имеет метод get()
    if hasattr(config, 'get') and callable(config.get):
        # Пробуем нижний регистр и как есть (на случай, если в БД лежит YANDEX_CLIENT_ID)
        val = config.get(key)
        if val:
            return val
        val = config.get(env_key)
        if val:
            return val
    elif isinstance(config, dict):
        # Старый способ для обычного dict
        if key in config and config[key]:
            return config[key]
        if env_key in config and config[env_key]:
            return config[env_key]

    return os.getenv(env_key, default or "")


def parse_last_updated(val):
    """
    Parse various timestamp formats returned by Yandex API.
    Accepts:
    - integer/float seconds since epoch
    - integer milliseconds since epoch
    - ISO 8601 string (with or without timezone)
    Returns a UTC `datetime` or None on failure.
    """
    if not val:
        return None
    try:
        # numeric types
        if isinstance(val, (int, float)):
            # if looks like milliseconds (greater than year 3000 in seconds)
            if val > 1e12:
                # milliseconds
                ts = val / 1000.0
            else:
                ts = float(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)

        # string types - try ISO formats
        if isinstance(val, str):
            # remove Z
            s = val.strip()
            if s.endswith('Z'):
                s = s[:-1]
            try:
                # try fromisoformat
                dt = datetime.fromisoformat(s)
                # convert to naive UTC if timezone-aware
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except Exception:
                # try common fallback formats
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(s.split('.')[0], fmt)
                    except Exception:
                        continue
    except Exception:
        return None
    return None
