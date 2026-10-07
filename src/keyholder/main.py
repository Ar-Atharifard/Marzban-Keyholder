import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from keyholder.api import admin, public
from keyholder.backends.marzban import MarzbanBackend
from keyholder.config import Settings
from keyholder.db import make_database
from keyholder.rate_limit import MemoryRateLimiter

logger = logging.getLogger("keyholder")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]  # Loaded from environment.
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.upstream_timeout, connect=5),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.backends = {"marzban-default": MarzbanBackend(settings, client)}
            yield
        engine.dispose()

    app = FastAPI(
        title="Keyholder", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.limiter = MemoryRateLimiter(settings.rate_limit_per_minute)
    app.include_router(public.router)
    app.include_router(admin.router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        # Pydantic errors contain input values: never echo credentials or public tokens.
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.middleware("http")
    async def safe_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.monotonic()
        path = request.url.path
        peer = request.client.host if request.client else "unknown"
        if path.startswith("/s/"):
            # Hash even malformed/Unicode tokens safely; never retain or log the raw token.
            digest = hashlib.sha256(path.removeprefix("/s/").encode("utf-8")).hexdigest()
            bucket = "subscription:" + digest
        elif path == "/admin" or path.startswith("/admin/"):
            bucket = "admin:" + peer
        else:
            bucket = "public:" + peer
        if not app.state.limiter.allow(bucket):
            response: Response = JSONResponse(
                {"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"}
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Never log exception objects: HTTP libraries may embed secret URLs.
                response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                }
            )
        )
        return response

    return app
