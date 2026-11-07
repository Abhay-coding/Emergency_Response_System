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
from app.database import Base, engine, get_db, init_db
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
    if settings.environment == "production":
        from sqlalchemy import inspect
        if not inspect(engine).has_table("medical_alerts"):
            raise RuntimeError("Run Alembic migrations before starting the production API")
    else:
        init_db()
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

# CORS - Configurable
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# Include routers
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
async def health(request: Request, db: Session = Depends(get_db)):
    """Health check endpoint with database connectivity check"""
    # Check database connectivity
    db_healthy = False
    db_error = None
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception as e:
        db_error = str(e)

    # Check Redis connectivity if configured
    redis_healthy = None
    if settings.redis_url:
        try:
            import redis
            r = redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
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
async def readiness(request: Request, db: Session = Depends(get_db)):
    """Readiness probe - checks if app is ready to serve traffic"""
    try:
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
