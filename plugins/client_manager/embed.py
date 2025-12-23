"""
Запуск/остановка внешнего/встроенного client-manager-service
Механизм: запускает `client-manager-service/run_server.py` в subprocess и возвращает Popen.
Используется для режима CM_MODE=embedded.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Optional, Dict, Any
import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

PROCESS: Optional[subprocess.Popen] = None
_MONITOR_THREAD: Optional[threading.Thread] = None
_SHOULD_MONITOR = False


def _get_run_script_path() -> str:
    """Find run_server.py in multiple possible locations."""
    # Попытка 1: Относительно этого файла (для разработки)
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    path = os.path.join(base, "client-manager-service", "run_server.py")
    if os.path.exists(path):
        return path

    # Попытка 2: Из переменной окружения WORKSPACE
    workspace = os.getenv("WORKSPACE")
    if workspace:
        path = os.path.join(workspace, "client-manager-service", "run_server.py")
        if os.path.exists(path):
            return path

    # Попытка 3: Из переменной окружения NEWHOMECONSOLE_HOME
    home = os.getenv("NEWHOMECONSOLE_HOME")
    if home:
        path = os.path.join(home, "client-manager-service", "run_server.py")
        if os.path.exists(path):
            return path

    # Попытка 4: Абсолютный путь для Docker (/app/...)
    path = "/app/client-manager-service/run_server.py"
    if os.path.exists(path):
        return path

    # Попытка 5: Проверить в текущей директории
    path = "./client-manager-service/run_server.py"
    if os.path.exists(path):
        return path

    # Возвращаем первый вариант (для сообщения об ошибке)
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(base, "client-manager-service", "run_server.py")


def start_embedded(env: dict | None = None, timeout: float = 5.0) -> subprocess.Popen:
    """Start client-manager-service as a separate process.

    Returns subprocess.Popen object. If already started, returns existing process.
    Raises FileNotFoundError if run_server.py cannot be found.
    """
    global PROCESS
    if PROCESS and PROCESS.poll() is None:
        logger.warning("Embedded client-manager-service is already running, returning existing process")
        return PROCESS

    run_path = _get_run_script_path()
    if not os.path.exists(run_path):
        # Log all attempted paths for debugging
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        attempted = [
            os.path.join(base, "client-manager-service", "run_server.py"),
            f"{os.getenv('WORKSPACE', 'N/A')}/client-manager-service/run_server.py",
            f"{os.getenv('NEWHOMECONSOLE_HOME', 'N/A')}/client-manager-service/run_server.py",
            "/app/client-manager-service/run_server.py",
            "./client-manager-service/run_server.py"
        ]
        raise FileNotFoundError(
            f"run_server.py not found. Attempted paths:\n" + "\n".join(attempted)
        )

    python = sys.executable or "python"
    cmd = [python, run_path]

    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    
    # Установим CM_MODE=embedded если не задан
    if 'CM_MODE' not in env_vars:
        env_vars['CM_MODE'] = 'embedded'

    # Start detached process (so it lives with core process)
    try:
        PROCESS = subprocess.Popen(
            cmd,
            env=env_vars,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        # Небольшая пауза, чтобы процесс успел подняться
        t0 = time.time()
        while time.time() - t0 < timeout:
            if PROCESS.poll() is None:
                # process still running - consider started
                logger.info(f"✅ Started embedded client-manager-service (pid={PROCESS.pid})")
                
                # Запустим мониторинг процесса
                start_monitoring()
                
                return PROCESS
            time.sleep(0.1)

        # Если процесс завершился до таймаута, это ошибка
        exit_code = PROCESS.poll()
        PROCESS = None
        raise RuntimeError(f"Embedded client-manager-service exited quickly with code: {exit_code}")
    
    except Exception as e:
        logger.error(f"❌ Failed to start embedded client-manager-service: {e}")
        PROCESS = None
        raise


def stop_embedded() -> None:
    """Terminate started process (if any)."""
    global PROCESS, _SHOULD_MONITOR
    if not PROCESS:
        logger.info("No embedded process to stop")
        return

    # Остановим мониторинг
    _SHOULD_MONITOR = False
    
    try:
        logger.info(f"Stopping embedded client-manager-service (pid={PROCESS.pid})...")
        
        # Try graceful terminate
        PROCESS.send_signal(signal.SIGINT)
        try:
            PROCESS.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            logger.warning("Graceful shutdown timed out, terminating...")
            PROCESS.terminate()
            PROCESS.wait(timeout=3.0)
        except Exception as e:
            logger.warning(f"Error during graceful shutdown: {e}")
            
    except subprocess.TimeoutExpired:
        logger.error("Process termination timed out, killing...")
        try:
            PROCESS.kill()
        except Exception as e:
            logger.error(f"Error killing process: {e}")
    except Exception as e:
        logger.error(f"Error stopping embedded process: {e}")
        try:
            PROCESS.kill()
        except Exception:
            pass
    finally:
        PROCESS = None
        logger.info("Embedded client-manager-service stopped")


def is_running() -> bool:
    """Check if embedded process is running."""
    global PROCESS
    return PROCESS is not None and PROCESS.poll() is None


def get_process_info() -> Dict[str, Any]:
    """Get information about the embedded process."""
    global PROCESS
    if PROCESS and PROCESS.poll() is None:
        return {
            "pid": PROCESS.pid,
            "running": True,
            "status": "running",
            "cmd": PROCESS.args if hasattr(PROCESS, 'args') else 'unknown'
        }
    else:
        return {
            "pid": PROCESS.pid if PROCESS else None,
            "running": False,
            "status": "stopped" if PROCESS else "not_started",
            "exit_code": PROCESS.poll() if PROCESS else None
        }


def start_monitoring():
    """Start monitoring thread for the embedded process."""
    global _MONITOR_THREAD, _SHOULD_MONITOR
    
    if _MONITOR_THREAD and _MONITOR_THREAD.is_alive():
        return  # Already monitoring
    
    _SHOULD_MONITOR = True
    
    def monitor():
        global PROCESS, _SHOULD_MONITOR
        while _SHOULD_MONITOR and PROCESS:
            if PROCESS.poll() is not None:  # Process has exited
                logger.error(f"Embedded client-manager-service (pid={PROCESS.pid}) has exited unexpectedly")
                # Try to restart if needed (could be configurable)
                break
            time.sleep(1)  # Check every second
        
        if _SHOULD_MONITOR and PROCESS and PROCESS.poll() is not None:
            logger.info("Monitoring stopped due to process exit")
    
    _MONITOR_THREAD = threading.Thread(target=monitor, daemon=True)
    _MONITOR_THREAD.start()


def stop_monitoring():
    """Stop monitoring thread."""
    global _SHOULD_MONITOR
    _SHOULD_MONITOR = False
    if _MONITOR_THREAD and _MONITOR_THREAD.is_alive():
        _MONITOR_THREAD.join(timeout=1.0)


# Enhanced API for mode management
class EmbeddedProcessManager:
    """Enhanced manager for embedded processes."""
    
    def __init__(self):
        self._process = None
        self._env = None
        self._monitor_thread = None
        self._should_monitor = False
        self._lock = threading.Lock()
    
    def start(self, env: dict | None = None, timeout: float = 5.0) -> subprocess.Popen:
        """Start embedded process with enhanced management."""
        with self._lock:
            if self._process and self._process.poll() is None:
                logger.warning("Embedded process already running")
                return self._process
            
            self._env = env
            self._process = start_embedded(env, timeout)
            return self._process
    
    def stop(self) -> None:
        """Stop embedded process."""
        with self._lock:
            if self._process:
                stop_embedded()
                self._process = None
    
    def restart(self, env: dict | None = None, timeout: float = 5.0) -> subprocess.Popen:
        """Restart embedded process."""
        with self._lock:
            self.stop()
            return self.start(env, timeout)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of embedded process."""
        with self._lock:
            return get_process_info()
    
    def is_alive(self) -> bool:
        """Check if embedded process is alive."""
        with self._lock:
            return is_running()


# Global instance for backward compatibility
_embedded_manager = EmbeddedProcessManager()


def start_embedded_with_manager(env: dict | None = None, timeout: float = 5.0) -> subprocess.Popen:
    """Start embedded process using enhanced manager."""
    return _embedded_manager.start(env, timeout)


def stop_embedded_with_manager() -> None:
    """Stop embedded process using enhanced manager."""
    _embedded_manager.stop()


def restart_embedded_with_manager(env: dict | None = None, timeout: float = 5.0) -> subprocess.Popen:
    """Restart embedded process using enhanced manager."""
    return _embedded_manager.restart(env, timeout)


def get_embedded_status() -> Dict[str, Any]:
    """Get status of embedded process using enhanced manager."""
    return _embedded_manager.get_status()


__all__ = [
    "start_embedded", 
    "stop_embedded", 
    "is_running", 
    "get_process_info",
    "start_monitoring",
    "stop_monitoring",
    "EmbeddedProcessManager",
    "start_embedded_with_manager",
    "stop_embedded_with_manager", 
    "restart_embedded_with_manager",
    "get_embedded_status"
]