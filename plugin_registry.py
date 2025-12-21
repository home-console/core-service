import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ExternalPlugin:
    id: str
    base_url: str
    health_url: Optional[str] = None
    auth_type: Optional[str] = None
    auth_token: Optional[str] = None
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    is_healthy: bool = False
    last_check: Optional[datetime] = None
    error_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # normalize urls
        self.base_url = self.base_url.rstrip('/')
        if not self.health_url:
            self.health_url = f"{self.base_url}/health"
        if not self.name:
            self.name = self.id


class ExternalPluginRegistry:
    """Registry for external HTTP/Docker plugins.

    Responsibilities:
    - store plugin descriptors
    - perform HTTP proxy requests with retries
    - run health checks
    """

    def __init__(self) -> None:
        self.plugins: Dict[str, ExternalPlugin] = {}
        self._http_client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        logger.info("ExternalPluginRegistry initialized")

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def register(
        self,
        plugin_id: str,
        base_url: str,
        health_url: Optional[str] = None,
        auth_type: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: float = 30.0,
        name: Optional[str] = None,
        version: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> ExternalPlugin:
        plugin = ExternalPlugin(
            id=plugin_id,
            base_url=base_url,
            health_url=health_url,
            auth_type=auth_type,
            auth_token=auth_token,
            timeout=timeout,
            max_retries=int(kwargs.get('max_retries', 3)),
            retry_delay=float(kwargs.get('retry_delay', 1.0)),
            name=name,
            version=version,
            description=description,
            metadata=kwargs.get('metadata', {}),
        )
        self.plugins[plugin_id] = plugin
        logger.info(f"Registered external plugin: {plugin_id} -> {plugin.base_url}")
        return plugin

    def unregister(self, plugin_id: str) -> bool:
        if plugin_id in self.plugins:
            del self.plugins[plugin_id]
            logger.info(f"Unregistered plugin: {plugin_id}")
            return True
        return False

    def get_plugin(self, plugin_id: str) -> Optional[ExternalPlugin]:
        return self.plugins.get(plugin_id)

    def list_plugins(self) -> List[ExternalPlugin]:
        return list(self.plugins.values())

    def is_registered(self, plugin_id: str) -> bool:
        return plugin_id in self.plugins

    async def proxy_request(
        self,
        plugin_id: str,
        path: str,
        method: str = "GET",
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        retry: bool = True,
    ) -> Any:
        """Proxy an HTTP request to the external plugin.

        Raises httpx.HTTPError or returns parsed JSON/text.
        """
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            raise LookupError(f"Plugin '{plugin_id}' not registered")

        path = path.lstrip('/')
        url = f"{plugin.base_url}/{path}"

        req_headers = dict(headers or {})
        # attach auth
        if plugin.auth_type == 'bearer' and plugin.auth_token:
            req_headers.setdefault('Authorization', f"Bearer {plugin.auth_token}")
        elif plugin.auth_type == 'api_key' and plugin.auth_token:
            req_headers.setdefault('X-API-Key', plugin.auth_token)

        request_timeout = timeout or plugin.timeout
        max_attempts = plugin.max_retries if retry else 1

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self.http_client.request(
                    method=method.upper(),
                    url=url,
                    json=json,
                    params=params,
                    headers=req_headers,
                    timeout=request_timeout,
                )
                resp.raise_for_status()
                plugin.error_count = 0
                try:
                    return resp.json()
                except Exception:
                    return resp.text

            except httpx.HTTPStatusError as e:
                plugin.error_count += 1
                last_exc = e
                status = e.response.status_code if e.response is not None else None
                logger.error(f"HTTP error from {plugin_id}: {status} (attempt {attempt})")
                if status and 400 <= status < 500:
                    raise
                if attempt < max_attempts:
                    await asyncio.sleep(plugin.retry_delay)
                    continue
                raise

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.TimeoutException) as e:
                plugin.error_count += 1
                last_exc = e
                logger.error(f"Connection error to {plugin_id}: {e} (attempt {attempt})")
                if attempt < max_attempts:
                    await asyncio.sleep(plugin.retry_delay)
                    continue
                raise

            except Exception as e:
                plugin.error_count += 1
                last_exc = e
                logger.exception(f"Unexpected error proxying to {plugin_id}: {e}")
                raise

        # if we end up here, raise last exception
        if last_exc:
            raise last_exc
        raise RuntimeError("Unknown proxy error")

    async def health_check(self, plugin_id: str) -> bool:
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            return False
        try:
            resp = await self.http_client.get(plugin.health_url, timeout=5.0)
            healthy = resp.status_code == 200
            plugin.is_healthy = healthy
            plugin.last_check = datetime.utcnow()
            if healthy:
                plugin.error_count = 0
            return healthy
        except Exception as e:
            plugin.is_healthy = False
            plugin.last_check = datetime.utcnow()
            plugin.error_count += 1
            logger.debug(f"Health check failed for {plugin_id}: {e}")
            return False

    async def health_check_all(self) -> Dict[str, bool]:
        results: Dict[str, bool] = {}
        for pid in list(self.plugins.keys()):
            results[pid] = await self.health_check(pid)
        return results


# singleton instance
external_plugin_registry = ExternalPluginRegistry()

__all__ = ["ExternalPlugin", "ExternalPluginRegistry", "external_plugin_registry"]
