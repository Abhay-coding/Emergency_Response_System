from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from pathlib import Path

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.constants import (
    DEFAULT_ALLOWED_METHODS,
    DEFAULT_ALLOWED_HEADERS,
    DEFAULT_EXPOSE_HEADERS,
)
from app.core.config import settings
from app.database import Base, engine, get_db, get_db_context, init_db
from app import models
from app.routers import auth, incidents, medical_alerts, campus
import structlog
import time

# Structured logging
if settings.log_format == "json":
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
else:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
logger = structlog.get_logger()


# Request size limit middleware
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10 MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Limit request body size to prevent DoS attacks"""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Request body too large. Maximum size: {MAX_REQUEST_SIZE} bytes"
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    # Paths that need relaxed CSP for Swagger UI
    DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # HSTS - only on HTTPS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # CSP - relax for docs paths to allow Swagger UI
        if request.url.path in self.DOCS_PATHS:
            # Relaxed CSP for Swagger UI
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "font-src 'self' https://cdn.jsdelivr.net; "
                "connect-src 'self'"
            )
        elif request.url.path in {"/", "/index.html"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        else:
            # Strict CSP for API endpoints
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )

        # Frame options
        response.headers["X-Frame-Options"] = "DENY"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = "nosniff"
        # X-XSS-Protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(self), microphone=(), camera=()"
        # Cross-Origin-Opener-Policy
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # Cross-Origin-Resource-Policy
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")

        # Log request
        logger.info(
            "request_started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )

        response = await call_next(request)

        # Log response
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    if settings.data_api_enabled:
        logger.info("data_api_mode_enabled")
    elif settings.environment == "production":
        from sqlalchemy import inspect
        if not inspect(engine).has_table("medical_alerts"):
            raise RuntimeError("Run Alembic migrations before starting the production API")
    else:
        init_db()

    # Seed campus places once at startup
    if not settings.data_api_enabled:
        from app.database import SessionLocal
        from app.routers.medical_alerts import seed_places
        with SessionLocal() as db:
            seed_places(db)

    # Start token blacklist background cleanup thread (only once per process)
    from app.core.token_blacklist import token_blacklist
    token_blacklist.start_background_cleanup()

    logger.info("application_started", app_name=settings.app_name, environment=settings.environment)
    yield
    # Shutdown
    logger.info("application_shutdown")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Campus medical assistance request and response API",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production unless explicitly enabled
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request size limit (custom middleware)
app.add_middleware(RequestSizeLimitMiddleware)

# Security headers (custom middleware)
app.add_middleware(SecurityHeadersMiddleware)

# Request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Request ID middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    import uuid
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# CORS - Configurable with production validation
if settings.environment == "production":
    if not settings.cors_origins or "*" in settings.cors_origins:
        raise RuntimeError("CORS origins must be explicitly configured for production (no wildcards)")
    if not settings.allowed_hosts:
        raise RuntimeError("allowed_hosts must be configured for production")
    cors_origins = settings.cors_origins
else:
    # In development, use dev_cors_origins if cors_origins is not explicitly set
    cors_origins = settings.cors_origins if settings.cors_origins else settings.dev_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=DEFAULT_ALLOWED_METHODS,
    allow_headers=DEFAULT_ALLOWED_HEADERS,
    expose_headers=DEFAULT_EXPOSE_HEADERS,
)

# Allowed hosts middleware for production
if settings.environment == "production" and settings.allowed_hosts:
    from starlette.middleware.hosts import HostMiddleware
    app.add_middleware(HostMiddleware, allowed_hosts=settings.allowed_hosts)

# Include routers
if settings.data_api_enabled:
    from app.routers import data_api_demo
    app.include_router(data_api_demo.router, prefix="/api/v1")
else:
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(medical_alerts.router, prefix="/api/v1")
    app.include_router(campus.router, prefix="/api/v1")

# Serve frontend static files (CSS, JS, images)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/style.css", include_in_schema=False)
async def frontend_stylesheet():
    return FileResponse(frontend_dir / "style.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
async def frontend_script():
    return FileResponse(frontend_dir / "app.js", media_type="application/javascript")


@app.get("/", tags=["System"], include_in_schema=False)
@limiter.limit("60/minute")
async def root(request: Request):
    """Serve the frontend SPA"""
    index_file = frontend_dir / "medical.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "message": settings.app_name,
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs" if settings.environment != "production" else "disabled",
        "health": settings.health_check_path,
    }


@app.get(settings.health_check_path, tags=["System"])
@limiter.limit("120/minute")
async def health(request: Request):
    """Health check endpoint with database connectivity check"""
    # Check database connectivity
    db_healthy = False
    db_error = None
    try:
        if settings.data_api_enabled:
            from app.data_api_repository import get_repo
            get_repo().query("SELECT 1")
        else:
            with get_db_context() as db:
                db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception as e:
        db_error = str(e)

    # Check Redis connectivity if configured
    redis_healthy = None
    if settings.redis_url:
        try:
            import redis
            # Enforce TLS in production
            ssl_cert_reqs = None
            if settings.environment == "production":
                if not settings.redis_url.startswith("rediss://"):
                    redis_healthy = False
                    logger.warning("Redis URL must use rediss:// (TLS) in production")
                else:
                    ssl_cert_reqs = "required"
            else:
                ssl_cert_reqs = None

            r = redis.from_url(
                settings.redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
                ssl_cert_reqs=ssl_cert_reqs
            )
            r.ping()
            redis_healthy = True
        except Exception:
            redis_healthy = False

    status = "healthy" if db_healthy and (redis_healthy is None or redis_healthy) else "unhealthy"

    response = {
        "status": status,
        "version": "1.0.0",
        "environment": settings.environment,
        "checks": {
            "database": "ok" if db_healthy else "failed",
        }
    }

    if settings.redis_url:
        response["checks"]["redis"] = "ok" if redis_healthy else "failed"

    if db_error:
        response["checks"]["database_error"] = db_error

    # Return 503 if unhealthy
    if status == "unhealthy":
        return JSONResponse(content=response, status_code=503)

    return response


@app.get(settings.metrics_path, tags=["System"])
async def metrics():
    """Prometheus metrics endpoint"""
    if not settings.enable_metrics:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Readiness probe endpoint (for Kubernetes/ECS)
@app.get("/ready", tags=["System"])
@limiter.limit("60/minute")
async def readiness(request: Request):
    """Readiness probe - checks if app is ready to serve traffic"""
    try:
        if settings.data_api_enabled:
            from app.data_api_repository import get_repo
            get_repo().query("SELECT 1")
        else:
            with get_db_context() as db:
                db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(
            content={"status": "not_ready", "error": str(e)},
            status_code=503
        )


# Liveness probe endpoint (for Kubernetes/ECS)
@app.get("/live", tags=["System"])
def liveness():
    """Liveness probe - checks if app is alive"""
    return {"status": "alive"}
