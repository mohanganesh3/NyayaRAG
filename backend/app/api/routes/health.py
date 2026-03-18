from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.session import check_database_connection
from app.schemas.system import HealthCheckResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthCheckResponse)
def healthcheck() -> JSONResponse:
    settings = get_settings()
    database_ok, error = check_database_connection()

    payload = {
        "service": "nyayarag-backend",
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "status": "ok" if database_ok else "degraded",
        "checks": {
            "database": {
                "status": "ok" if database_ok else "error",
                "detail": None if database_ok else error,
            }
        },
    }

    response_status = status.HTTP_200_OK if database_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=response_status, content=payload)
