from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.database import SessionLocal
from app.routers import alerts, auth, bottlenecks, dashboard, data, departments, explain, flow, forecast, recommendations, resources, simulation, optimization, integration, stream
from app.routers import settings as settings_router
from app.security.dependencies import get_current_admin
from app.seed import init_db, seed

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(
    title=settings.app_name,
    description="Academic operational analytics prototype. Not a certified clinical system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# Uniform error body: {error, detail, code}
@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": exc.detail, "code": exc.status_code},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    # Only field locations and messages are returned; submitted values (e.g. passwords) are never echoed.
    detail = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": detail, "code": 422})


@app.get(f"{settings.api_prefix}/health", tags=["system"])
def health():
    return {"status": "ok", "service": "hospital-ops-ai", "version": app.version}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(departments.router, prefix=settings.api_prefix)
app.include_router(data.router, prefix=settings.api_prefix, dependencies=[Depends(get_current_admin)])
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(flow.router, prefix=settings.api_prefix)
app.include_router(resources.router, prefix=settings.api_prefix)
app.include_router(bottlenecks.router, prefix=settings.api_prefix)
app.include_router(forecast.router, prefix=settings.api_prefix)
app.include_router(explain.router, prefix=settings.api_prefix)
app.include_router(recommendations.router, prefix=settings.api_prefix)
app.include_router(simulation.router, prefix=settings.api_prefix)
app.include_router(optimization.router, prefix=settings.api_prefix)
app.include_router(integration.router, prefix=settings.api_prefix)
app.include_router(stream.router, prefix=settings.api_prefix)
app.include_router(alerts.router, prefix=settings.api_prefix)
app.include_router(settings_router.router, prefix=settings.api_prefix)
