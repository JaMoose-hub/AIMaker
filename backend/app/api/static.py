"""Static file serving for the built frontend (SPA) with fallback.

If config.frontend_dist contains an index.html, it is mounted at "/" with an
SPA fallback (unknown non-API paths return index.html). Otherwise GET /
returns a small info page and the API keeps working.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

log = logging.getLogger(__name__)

_INFO_PAGE = """<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>Board Vision</title></head>
<body style="font-family: system-ui, sans-serif; margin: 3rem;">
<h1>Board Vision backend</h1>
<p>Frontend not built - <code>frontend/dist</code> was not found.</p>
<p>Build it with <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>,
then restart the server.</p>
<p>The API is up: try <a href="/api/config">/api/config</a> or the
<a href="/video">/video</a> MJPEG stream.</p>
</body></html>"""


class SPAStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for unknown paths (SPA routing)."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


def mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    index = dist_dir / "index.html"
    if index.is_file():
        app.mount("/", SPAStaticFiles(directory=str(dist_dir), html=True), name="frontend")
        log.info("serving frontend from %s", dist_dir)
        return

    log.warning("frontend dist not found at %s - serving info page", dist_dir)

    @app.get("/", include_in_schema=False)
    async def frontend_not_built() -> HTMLResponse:
        return HTMLResponse(_INFO_PAGE, status_code=200)
