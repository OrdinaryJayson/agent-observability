from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from sqlalchemy import text

from app.api.routes import router
from app.core.config import cors_origins
from app.core.database import get_engine
from app.core.errors import AppError
from app.models.tables import tables
from app.repositories.execution import fail_running
from app.schemas.api import ErrorResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    tables()  # Fail fast if migrations were not run.
    with get_engine().begin() as conn:
        fail_running(conn, "Backend restarted before trace persistence")
    yield
    get_engine().dispose()


app = FastAPI(
    title="Agent Observability Prototype",
    version="0.1.0",
    lifespan=lifespan,
    responses={code: {"model": ErrorResponse} for code in (404, 409, 422, 500)},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


def error(status, code, message, details=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return error(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Do not reflect the original request body (possibly credentials) in errors.
    return error(
        422,
        "VALIDATION_ERROR",
        "Request validation failed",
        {
            "fields": [
                {"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()
            ],
        },
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return error(
        exc.status_code,
        "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
        "Request could not be processed",
    )


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    return error(500, "INTERNAL_ERROR", "Internal server error")


@app.get("/health", tags=["operations"])
def health():
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(router)
