"""
api/main/static.py — mounts the built React frontend (or a dev-mode
fallback JSON root) onto the FastAPI app.

Split out of the old single api/main.py (2026-08-01, file-size cleanup);
no logic changed, only relocated into a callable so __init__.py can invoke
it after both `app` and the repo ROOT path are available.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


def mount_frontend(app: FastAPI, root: Path) -> None:
    """Serve the built React frontend from `root`/frontend/dist, or a
    dev-mode JSON placeholder if it hasn't been built yet."""
    _DIST = root / "frontend" / "dist"

    if _DIST.exists():
        # Serve static assets (JS, CSS, images)
        app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")
        # Public images copied by Vite are emitted under dist/images.  Mount the
        # directory instead of relying on the SPA catch-all, which returns
        # index.html and makes a browser display a broken image icon.
        _images = _DIST / "images"
        if _images.exists():
            app.mount("/images", StaticFiles(directory=str(_images)), name="images")
        # Coach Celo lesson recordings are Vite public assets. Mount them before
        # the SPA catch-all so an <audio> request receives an MP3, not index.html.
        _audio = _DIST / "audio"
        if _audio.exists():
            app.mount("/audio", StaticFiles(directory=str(_audio)), name="audio")

        # ── Explicit static file routes BEFORE the catch-all ─────────────────────
        # The catch-all /{full_path:path} would otherwise intercept any file
        # requests (favicon.svg, logo.png, robots.txt, etc.) and return index.html.
        # List every static file in dist/ root that the browser might request.
        _STATIC_ROOT_FILES = ["favicon.svg", "favicon.ico", "favicon.png",
                              "celo-favicon-20260909.svg",
                              "logo.png", "logo.svg", "mascot.png",
                              "robots.txt", "site.webmanifest"]
        for _fname in _STATIC_ROOT_FILES:
            _fpath = _DIST / _fname
            if _fpath.exists():
                # Use a closure to capture _fpath correctly inside the loop
                def _make_handler(p: Path):
                    async def _handler():
                        return FileResponse(str(p))
                    return _handler
                app.get(f"/{_fname}", include_in_schema=False)(_make_handler(_fpath))

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            """Catch-all: serve index.html for all non-API routes (React Router).
            Cache-Control: no-cache forces browsers to always revalidate index.html.
            JS/CSS assets have content-hashed filenames so they stay cached correctly.
            Without this, a browser caches the old index.html and keeps loading the
            old JS bundle even after a deploy — causing auth failures and blank charts.
            """
            index = _DIST / "index.html"
            return FileResponse(str(index), headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
    else:
        @app.get("/", include_in_schema=False)
        async def dev_root() -> dict:
            return {
                "status": "API running",
                "note": "React frontend not built yet. Run: cd frontend && npm run build",
                "docs": "/docs",
            }
