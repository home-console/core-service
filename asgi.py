"""
ASGI entry point for uvicorn with hot reload support.
Creates FastAPI app at import time so uvicorn can use --reload.
"""
import os
import sys

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

# Import app factory - use relative imports which work when imported as core_service.asgi
from .app import create_admin_app

# Create app instance
app = create_admin_app()
