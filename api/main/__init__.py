"""
api/main/ — FastAPI application entry point.

Run with:  uvicorn api.main:app --host 0.0.0.0 --port 8501 --reload

Split out of the old single api/main.py (2026-08-01, file-size cleanup)
into:
  - bootstrap.py: sys.path insert + logger setup + db init (must run first)
  - lifespan.py:  auto-resume-on-restart + FastAPI lifespan hook
  - app.py:       FastAPI() instance, CORS middleware, router registration
  - static.py:    mounts the built React frontend / dev-mode fallback

Import order below reproduces the original flat file's exact top-to-bottom
execution order: bootstrap side effects first (sys.path/logger/db), then
app creation + router registration, then static file mounting. `app` is
re-exported here so `uvicorn api.main:app` keeps working unchanged.
"""
from __future__ import annotations

from api.main import bootstrap  # noqa: F401 — import for its side effects (sys.path, logger, db init)
from api.main.app import app
from api.main.static import mount_frontend

mount_frontend(app, bootstrap.ROOT)

__all__ = ["app"]
