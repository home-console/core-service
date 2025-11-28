import os

# Create Orchestrator and FastAPI app at import time so uvicorn can use
# an import string like `core_service.asgi:app` which enables --reload.
from .services import Orchestrator
from .admin_app import create_admin_app

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
orch = Orchestrator(project_root=project_root)

# Respect env var used elsewhere to disable the orchestrator in dev/tests
if not os.getenv("CORE_DISABLE_ORCHESTRATOR"):
    try:
        orch.start_all()
    except Exception:
        # Don't raise on import-time failures; let the app start and surface
        # errors in logs. This keeps behavior close to `main.py`.
        pass

app = create_admin_app(orch)
