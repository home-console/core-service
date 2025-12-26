"""
ASGI entry point for uvicorn with hot reload support.
Creates FastAPI app at import time so uvicorn can use --reload.
"""
import os
import sys
import logging

# Настроить логирование сразу
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

print("🔵 ASGI: Starting import...")
logger.info("🔵 ASGI: Starting import...")

# Ensure we're treated as part of core_service package
if not __package__:
    __package__ = 'core_service'

# Get current file directory and calculate paths
_current_file = os.path.abspath(__file__)
_current_dir = os.path.dirname(_current_file)
_parent_dir = os.path.dirname(_current_dir)  # /app/core_service -> /app

# Ensure parent directory (/app) is in Python path for imports
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

print("🔵 ASGI: About to import create_admin_app...")
logger.info("🔵 ASGI: About to import create_admin_app...")

# Import app instance directly - it's created at module level in app.py
print("🔵 ASGI: About to import app...")
sys.stdout.flush()

from .app import app

print("✅ ASGI: Successfully imported app")
logger.info("✅ ASGI: Successfully imported app")
sys.stdout.flush()
