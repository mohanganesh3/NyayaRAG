import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes.health import router as health_router
from app.api.routes.query import router as query_router
from app.api.routes.trust import router as trust_router
from app.api.routes.workspace import router as workspace_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
logger = logging.getLogger("nyayarag.backend")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application startup", extra={"event": "app_startup"})
    yield
    logger.info("application shutdown", extra={"event": "app_shutdown"})

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(health_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(trust_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "NyayaRAG Backend",
        "status": "foundation-ready",
        "docs": "/api/docs",
    }
