from typing import Dict
import sys
import os
import time
import http.client
from urllib.parse import urlparse
import threading
import subprocess
import signal
from .ManagedService import ManagedService


class Orchestrator:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.services: Dict[str, ManagedService] = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Реестр сервисов
        self.register(
            ManagedService(
                name="auth_service",
                command=[sys.executable, "main.py"],
                cwd=os.path.join(project_root, "auth_service"),
                healthcheck_url="http://127.0.0.1:8000/health",
            )
        )
        self.register(
            ManagedService(
                name="api_gateway",
                command=[sys.executable, os.path.join(project_root, "api_gateway", "main.py")],
                cwd=project_root,
                healthcheck_url="http://127.0.0.1:9000/health",
                depends_on=["auth_service"],
            )
        )
        self.register(
            ManagedService(
                name="client_manager",
                command=[sys.executable, os.path.join(project_root, "client_manager", "unified_server.py")],
                cwd=project_root,
                healthcheck_url="http://127.0.0.1:10000/api/clients",
                depends_on=["api_gateway"],
            )
        )

    def register(self, service: ManagedService) -> None:
        self.services[service.name] = service

    def _deps_healthy(self, svc: ManagedService) -> bool:
        if not svc.depends_on:
            return True
        for dep_name in svc.depends_on:
            dep = self.services.get(dep_name)
            if not dep or not self._is_running(dep) or not self._check_health(dep):
                return False
        return True

    def _wait_deps(self, svc: ManagedService, timeout_sec: int = 60) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline and not self._stop_event.is_set():
            if self._deps_healthy(svc):
                return True
            time.sleep(1)
        return self._deps_healthy(svc)

    def _record_restart(self, svc: ManagedService) -> None:
        now = time.time()
        svc._restart_timestamps.append(now)
        # чистим окно
        svc._restart_timestamps = [t for t in svc._restart_timestamps if now - t <= svc.restart_window_sec]
        # экспоненциальный backoff с верхней границей
        svc.restart_backoff_sec = min(int(max(1, svc.restart_backoff_sec * svc.backoff_multiplier)), svc.backoff_max_sec)

    def _should_throttle(self, svc: ManagedService) -> bool:
        now = time.time()
        svc._restart_timestamps = [t for t in svc._restart_timestamps if now - t <= svc.restart_window_sec]
        return len(svc._restart_timestamps) >= svc.restart_limit_in_window

    def _start_service(self, svc: ManagedService) -> None:
        # Ждём зависимости
        if not self._wait_deps(svc):
            print(f"⏳ Зависимости для {svc.name} не готовы, откладываем старт")
            return
        # Validate command list to avoid accidental shell invocation or injection
        if not isinstance(svc.command, (list, tuple)) or len(svc.command) == 0:
            print(f"❌ Invalid command for {svc.name}: expected non-empty list of args")
            return
        # ensure none of the args contain shell metacharacters
        for part in svc.command:
            if contains_shell_meta(str(part)):
                print(f"❌ Refusing to start {svc.name}: command argument contains unsafe characters: {part}")
                return

        now = time.time()
        backoff = max(0, svc.restart_backoff_sec - int(now - svc.last_start_ts))
        if backoff:
            time.sleep(backoff)
        svc.last_start_ts = time.time()
        if self._should_throttle(svc):
            print(f"🧯 Слишком частые рестарты {svc.name}, делаем паузу {svc.backoff_max_sec}s")
            time.sleep(svc.backoff_max_sec)
        svc.process = subprocess.Popen(
            svc.command,
            cwd=svc.cwd or self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        print(f"🚀 Запущен {svc.name} (pid={svc.process.pid})")

        # Потоки логов, чтобы не блокировать stdout/stderr
        threading.Thread(target=self._pipe_output, args=(svc, True), daemon=True).start()
        threading.Thread(target=self._pipe_output, args=(svc, False), daemon=True).start()

    @staticmethod
    def _http_get_ok(url: str, timeout: float = 3.0) -> bool:
        try:
            parsed = urlparse(url)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            conn.request("GET", path)
            resp = conn.getresponse()
            ok = 200 <= resp.status < 300
            conn.close()
            return ok
        except Exception:
            return False

    def _is_running(self, svc: ManagedService) -> bool:
        return svc.process is not None and svc.process.poll() is None

    def _check_health(self, svc: ManagedService) -> bool:
        if not svc.healthcheck_url:
            return True
        return self._http_get_ok(svc.healthcheck_url)

    def start_all(self) -> None:
        for svc in self.services.values():
            self._start_service(svc)

        threading.Thread(target=self._monitor_loop, daemon=True).start()

    # --- Admin helpers ---
    def get_services_status(self) -> Dict[str, Dict[str, str]]:
        status: Dict[str, Dict[str, str]] = {}
        for name, svc in self.services.items():
            running = self._is_running(svc)
            healthy = self._check_health(svc) if running else False
            status[name] = {
                "name": name,
                "running": "yes" if running else "no",
                "healthy": "yes" if healthy else "no",
                "pid": str(svc.process.pid) if running and svc.process else "-",
            }
        return status

    def restart(self, name: str) -> bool:
        svc = self.services.get(name)
        if not svc:
            return False
        self._restart_service(svc)
        return True

    def stop(self, name: str, graceful: bool = True) -> bool:
        svc = self.services.get(name)
        if not svc:
            return False
        self._stop_service(svc, graceful=graceful)
        return True

    def start(self, name: str) -> bool:
        svc = self.services.get(name)
        if not svc:
            return False
        if self._is_running(svc):
            return True
        self._start_service(svc)
        return True

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(30)  # Увеличиваем интервал с 2 до 30 секунд для уменьшения шума в логах
            for svc in list(self.services.values()):
                proc = svc.process
                if proc is None:
                    continue
                # Проверка завершения процесса
                ret = proc.poll()
                if ret is not None:
                    print(f"⚠️  {svc.name} завершился с кодом {ret}. Перезапуск...")
                    self._record_restart(svc)
                    self._start_service(svc)
                    continue
                # Healthcheck
                if not self._check_health(svc):
                    print(f"❌ Health-check провален у {svc.name}. Попытка мягкой перезагрузки...")
                    self._record_restart(svc)
                    self._restart_service(svc)

    def _restart_service(self, svc: ManagedService) -> None:
        self._stop_service(svc, graceful=True)
        self._start_service(svc)

    def _stop_service(self, svc: ManagedService, graceful: bool) -> None:
        proc = svc.process
        if not proc:
            return
        try:
            if graceful:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                proc.kill()
        finally:
            print(f"🛑 Остановлен {svc.name}")
            svc.process = None

    def stop_all(self, graceful: bool = True) -> None:
        self._stop_event.set()
        for svc in list(self.services.values()):
            self._stop_service(svc, graceful=graceful)


def contains_shell_meta(s: str) -> bool:
    """Module-level helper: detect shell metacharacters in a string."""
    return any(ch in s for ch in [';', '&', '|', '<', '>', '`', '$', '\\'])