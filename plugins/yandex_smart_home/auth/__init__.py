"""Authentication module for Yandex Smart Home."""
from ..models import YandexUser
from .manager import YandexAuthManager

"""Authentication module for Yandex Smart Home."""
from ..models import YandexUser
from .manager import YandexAuthManager

# Also expose helpers from the top-level auth.py module (compat shim)
try:
	from ..auth import AuthServiceClient, cfg_get  # type: ignore
except Exception:
	AuthServiceClient = None
	cfg_get = None

__all__ = ['YandexUser', 'YandexAuthManager', 'AuthServiceClient', 'cfg_get']
