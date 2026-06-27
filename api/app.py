"""FastAPI application factory for the Synapse AI Agent API.

Entry points
------------
``create_app()``
    Returns a configured ``FastAPI`` instance.  The compiled LangGraph is built
    once during the lifespan startup and stored on ``app.state.graph``.
    Route handlers retrieve it via ``request.app.state.graph``.

``run()``
    Convenience wrapper that reads host/port from ``config/configuration.yaml``
    (under the ``api:`` key) and starts a ``uvicorn`` server.

``__main__``
    ``python -m api.app`` calls ``run()``.

Graph lifecycle
---------------
The graph is built **once** at startup so the MemorySaver (or SQLite) checkpointer
is shared across all requests in a process.  Thread isolation is provided by
``thread_id`` in the LangGraph config -- each run gets its own UUID.

Error handling
--------------
``ResearchAnalystException`` is caught by a dedicated handler and returned as
``{"error": "...", "type": "ResearchAnalystException"}`` with HTTP 500.
Unhandled exceptions are caught by a generic handler and returned as
``{"error": "Internal server error", "detail": "..."}`` with HTTP 500.
Tracebacks are never leaked to clients; they are logged via ``GLOBAL_LOGGER``.

Owner: Ratul Sur
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=False)
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import router as auth_router
from api.dashboard import router as dashboard_router
from api.finance import router as finance_router
from api.routes import router
from db.session import init_db
from exception.custom_exception import ResearchAnalystException
from graph.builder import build_graph
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config


# ---------------------------------------------------------------------------
# Lifespan: build graph once at startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Build and attach the compiled LangGraph during application startup."""
    # Guard: JWT_SECRET must be present before we accept any traffic.
    if not os.environ.get("JWT_SECRET"):
        log.error(
            "api: JWT_SECRET environment variable is not set. "
            "Set it to a long random string before starting the server."
        )
        raise RuntimeError(
            "JWT_SECRET is required. Set it in your environment or .env file."
        )

    log.info("api: lifespan startup -- building research graph")
    try:
        app.state.graph = build_graph()
        log.info("api: research graph ready", graph_type=type(app.state.graph).__name__)
    except Exception as exc:
        log.error("api: failed to build graph at startup", error=str(exc))
        raise

    # Initialise the database (creates SQLite tables; logs a hint for Postgres).
    await init_db()

    yield  # application runs

    log.info("api: lifespan shutdown")
    # Nothing to clean up for MemorySaver; SQLite connections are managed by
    # the SqliteSaver context in persistence/checkpointer.py.


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(graph=None) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    graph:
        Optional pre-built compiled graph (useful for testing so the startup
        lifespan does not rebuild it).  When ``None`` (the default), the
        lifespan handler calls ``build_graph()`` at startup.

    Returns
    -------
    FastAPI
        Fully configured ASGI application.
    """
    cfg = load_config()
    api_cfg: dict = cfg.get("api", {})
    cors_origins: list[str] = api_cfg.get("cors_origins", ["*"])

    # When a pre-built graph is provided, skip the lifespan rebuild.
    if graph is not None:
        @asynccontextmanager
        async def _injected_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            log.info("api: lifespan startup -- using injected graph")
            app.state.graph = graph
            await init_db()
            yield
            log.info("api: lifespan shutdown")

        lifespan_ctx = _injected_lifespan
    else:
        lifespan_ctx = _lifespan

    app = FastAPI(
        title="Synapse AI Agent API",
        description=(
            "Research-report agent: start runs, approve/edit/reject the generated plan "
            "via the human-in-the-loop interrupt, and stream progress events."
        ),
        version="0.1.0",
        lifespan=lifespan_ctx,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS -- configured via api.cors_origins in configuration.yaml
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers ---

    @app.exception_handler(ResearchAnalystException)
    async def _research_exc_handler(
        request: Request, exc: ResearchAnalystException
    ) -> JSONResponse:
        """Surface ResearchAnalystException as a clean JSON 500 (no traceback)."""
        log.error(
            "api: ResearchAnalystException",
            message=exc.error_message,
            file=exc.file_name,
            line=exc.lineno,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": exc.error_message,
                "type": "ResearchAnalystException",
            },
        )

    @app.exception_handler(Exception)
    async def _generic_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all: log the exception and return a safe error message."""
        log.error(
            "api: unhandled exception",
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc),
            },
        )

    # --- Routes ---
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(finance_router)

    return app


# ---------------------------------------------------------------------------
# Uvicorn entrypoint
# ---------------------------------------------------------------------------


def run() -> None:
    """Start the API server using uvicorn.

    Reads ``api.host`` and ``api.port`` from ``config/configuration.yaml``.
    Uses the factory mode so uvicorn can call ``create_app()`` after forking
    worker processes.
    """
    cfg = load_config()
    api_cfg: dict = cfg.get("api", {})
    host: str = api_cfg.get("host", "0.0.0.0")
    # Railway (and other PaaS platforms) dynamically assign a port via the PORT
    # environment variable.  Prefer that over the YAML config value so the app
    # binds to whatever port the platform expects.  Falls back to the YAML
    # setting (default 8000) for local / Docker Compose usage.
    port: int = int(os.environ.get("PORT") or api_cfg.get("port", 8000))

    log.info("api: starting uvicorn", host=host, port=port)
    uvicorn.run(
        "api.app:create_app",
        host=host,
        port=port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    run()
