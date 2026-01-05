import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Periodic health monitor for external plugins.

    Usage:
        monitor = HealthMonitor(registry, check_interval=60, alert_callback=callable)
        await monitor.start()
        await monitor.stop()
    """

    def __init__(
        self,
        registry,
        check_interval: int = 60,
        alert_callback: Optional[Callable[[str, object], None]] = None,
    ) -> None:
        self.registry = registry
        self.check_interval = check_interval
        self.alert_callback = alert_callback
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            logger.warning("Health monitor already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Health monitor started (interval={self.check_interval}s)")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None
        logger.info("Health monitor stopped")

    async def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                results = await self.registry.health_check_all()
                for plugin_id, healthy in results.items():
                    if not healthy:
                        logger.warning(f"Plugin {plugin_id} unhealthy (errors={self.registry.get_plugin(plugin_id).error_count})")
                        if self.alert_callback:
                            try:
                                maybe = self.alert_callback(plugin_id, self.registry.get_plugin(plugin_id))
                                if asyncio.iscoroutine(maybe):
                                    await maybe
                            except Exception as e:
                                logger.exception(f"Health monitor alert callback failed: {e}")
            except Exception as e:
                logger.exception(f"Health monitor loop error: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
            except asyncio.TimeoutError:
                continue
