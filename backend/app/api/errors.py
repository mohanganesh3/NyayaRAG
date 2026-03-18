from collections.abc import Iterable

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.api import ErrorDetail, ErrorResponse


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    detail: dict[str, object] | list[dict[str, object]] | str | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, detail=detail),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _normalize_validation_errors(errors: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for error in errors:
        loc = error.get("loc")
        normalized.append(
            {
                "loc": [str(item) for item in loc] if isinstance(loc, tuple | list) else [],
                "msg": error.get("msg"),
                "type": error.get("type"),
            }
        )
    return normalized


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: object, exc: RequestValidationError) -> JSONResponse:
        return build_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="The request payload failed validation.",
            detail=_normalize_validation_errors(exc.errors()),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: object, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", "http_error"))
            message = str(exc.detail.get("message", "Request failed."))
            detail = exc.detail.get("detail")
        else:
            code = "http_error"
            message = str(exc.detail)
            detail = None

        return build_error_response(
            status_code=exc.status_code,
            code=code,
            message=message,
            detail=detail,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: object, exc: Exception) -> JSONResponse:
        return build_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_server_error",
            message="An unexpected server error occurred.",
            detail=exc.__class__.__name__,
        )
