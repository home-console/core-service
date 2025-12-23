#!/usr/bin/env python3
"""
Core Service: FastAPI приложение с плагинной системой.
Запускает admin API на порту 11000.
"""

import os
import sys
import uvicorn
from .app import create_admin_app
import signal


def main() -> None:
    print("🚀 Запуск Core Service...")

    def handle_signal(signum, frame):
        print("\n🔻 Получен сигнал остановки, завершение работы...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Запуск админ-панели (FastAPI) на 0.0.0.0:11000
    app = create_admin_app()

    reload_flag = True if os.getenv("CORE_RELOAD", "0") in ("1", "true", "True") else False
    # Note: when passing an ASGI application object to uvicorn.run(),
    # the automatic 'reload' feature cannot be enabled via import-string reloader.
    # Uvicorn prints a warning in that case. To avoid the noisy warning we
    # disable reload here and surface an informative message. If you need
    # true code-reload in dev, start uvicorn using the CLI with an import
    # string (for example: `uvicorn core_service.admin_app:app --reload`).
    if reload_flag:
        print("⚠️ CORE_RELOAD requested but running programmatically; starting without reload. To enable reload run uvicorn CLI with an import string.")
    
    uvicorn.run(app, host="0.0.0.0", port=11000, log_level="info", reload=False)


if __name__ == "__main__":
    main()

