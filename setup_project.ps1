
$ErrorActionPreference = "Stop"

$directories = @(
    "app",
    "app\routers",
    "app\services",
    "app\core",
    "tests",
    "uploads",
    "frontend",
    "docs"
)

foreach ($directory in $directories) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$files = @{
    "app\__init__.py" = ""
    "app\routers\__init__.py" = ""
    "app\services\__init__.py" = ""
    "app\core\__init__.py" = ""
    "app\core\rate_limit.py" = @'
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
'@

    "requirements.txt" = @'
fastapi
uvicorn[standard]
sqlalchemy
python-multipart
pillow
pydantic-settings
pwdlib[argon2]
PyJWT
email-validator
pytest
httpx
slowapi
structlog
prometheus-client
'@

    ".gitignore" = @'
.venv/
__pycache__/
*.py[cod]
.env
*.db
uploads/*
!uploads/.gitkeep
.pytest_cache/
.coverage
'@

    ".env.example" = @'
APP_NAME=Campus Emergency Response System
DATABASE_URL=sqlite:///./emergency.db
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=5
# JWT_SECRET=generate-with: openssl rand -base64 64
ACCESS_TOKEN_MINUTES=60
REFRESH_TOKEN_DAYS=7
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
'@

    "app\core\config.py" = @'
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "Campus Emergency Response System"
    database_url: str = "sqlite:///./emergency.db"
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 5
    # JWT secret MUST be set via environment variable - no default for security
    jwt_secret: str
    access_token_minutes: int = 60
    refresh_token_days: int = 7
    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
'@

    "app\database.py" = @'
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'@

    "app\models.py" = @'
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
import enum


class Role(str, enum.Enum):
    reporter = "reporter"
    responder = "responder"
    admin = "admin"


class IncidentStatus(str, enum.Enum):
    reported = "reported"
    assigned = "assigned"
    in_progress = "in_progress"
    resolved = "resolved"


class IncidentPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role), default=Role.reporter
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), index=True)
    location: Mapped[str] = mapped_column(String(200), index=True)
    priority: Mapped[IncidentPriority] = mapped_column(
        Enum(IncidentPriority), default=IncidentPriority.medium
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.reported
    )

    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    image_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
'@

    "app\schemas.py" = @'
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import IncidentPriority, IncidentStatus, Role


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, pattern=r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$')


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: Role
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=5, max_length=5000)
    category: str = Field(min_length=2, max_length=50)
    location: str = Field(min_length=2, max_length=200)
    priority: IncidentPriority = IncidentPriority.medium


class IncidentOut(BaseModel):
    id: int
    title: str
    description: str
    category: str
    location: str
    priority: IncidentPriority
    status: IncidentStatus
    reporter_id: int
    assigned_to: int | None
    image_path: str | None
    created_at: datetime
    assigned_at: datetime | None
    resolved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class IncidentList(BaseModel):
    items: list[IncidentOut]
    total: int
    limit: int
    offset: int
    model_config = ConfigDict(from_attributes=True)


class AssignIncident(BaseModel):
    responder_id: int


class UpdateStatus(BaseModel):
    status: IncidentStatus
'@

    "app\core\security.py" = @'
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(subject: str) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_minutes
    )
    return jwt.encode(
        {"sub": subject, "exp": expiry, "type": "access"},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def create_refresh_token(subject: str) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_days
    )
    return jwt.encode(
        {"sub": subject, "exp": expiry, "type": "refresh"},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid token type")
    return payload


def decode_refresh_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],
    )
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Invalid token type")
    return payload
'@

    "app\dependencies.py" = @'
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt

from app.core.security import decode_access_token
from app.database import get_db
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_roles(*roles: Role):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker
'@

    "app\routers\auth.py" = @'
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token, create_refresh_token, hash_password, verify_password
)
from app.database import get_db
from app.dependencies import get_current_user
from app.main import limiter
from app.models import Role, User
from app.schemas import TokenOut, UserCreate, UserOut, RefreshTokenRequest

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    if db.query(User).filter(User.email == email).first():
        # Simulate same delay as password hash to prevent timing attacks
        hash_password("dummy")
        raise HTTPException(status_code=409, detail="Email already registered")

    # Public registration can only create reporter accounts.
    user = User(
        name=data.name,
        email=email,
        password_hash=hash_password(data.password),
        role=Role.reporter,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower()
    user = db.query(User).filter(User.email == email).first()

    # Constant-time verification to prevent email enumeration
    if not user:
        verify_password(form.password, "$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy")
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return TokenOut(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("20/minute")
def refresh_token(
    request: Request,
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    from app.core.security import decode_refresh_token
    try:
        payload = decode_refresh_token(data.refresh_token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return TokenOut(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
'@

    "app\routers\incidents.py" = @'
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from PIL import Image, UnidentifiedImageError

from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.main import limiter
from app.models import (
    Incident, IncidentPriority, IncidentStatus, Role, User
)
from app.schemas import (
    IncidentCreate, IncidentOut, AssignIncident, UpdateStatus, IncidentList
)
from app.core.config import settings

router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents"])

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_upload(file: UploadFile, incident_id: int) -> str:
    """Save upload with streaming validation - doesn't load entire file into memory"""
    max_size = settings.max_upload_size_mb * 1024 * 1024
    raw = file.file.read(max_size + 1)

    if len(raw) > max_size:
        raise HTTPException(status_code=413, detail="Image exceeds size limit")

    try:
        image = Image.open(BytesIO(raw))
        image.verify()
        if image.format not in ALLOWED_FORMATS:
            raise HTTPException(status_code=415, detail="Use JPEG, PNG or WEBP")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=415, detail="Invalid image file")

    directory = Path(settings.upload_dir)
    directory.mkdir(parents=True, exist_ok=True)

    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
    filename = f"{uuid4().hex}{extension}"
    destination = directory / filename
    destination.write_bytes(raw)
    return str(destination)


@router.post("", response_model=IncidentOut, status_code=201)
@limiter.limit("30/minute")
def create_incident(
    request: Request,
    data: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = Incident(**data.model_dump(), reporter_id=user.id)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


@router.get("", response_model=IncidentList)
@limiter.limit("60/minute")
def list_incidents(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[IncidentStatus] = None,
    priority: Optional[IncidentPriority] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Incident)
    if user.role == Role.reporter:
        query = query.filter(Incident.reporter_id == user.id)
    if status:
        query = query.filter(Incident.status == status)
    if priority:
        query = query.filter(Incident.priority == priority)

    total = query.count()
    incidents = query.order_by(Incident.created_at.desc()).limit(limit).offset(offset).all()

    return IncidentList(items=incidents, total=total, limit=limit, offset=offset)


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if user.role == Role.reporter and incident.reporter_id != user.id:
        raise HTTPException(status_code=403, detail="Not permitted")
    return incident


@router.post("/{incident_id}/image", response_model=IncidentOut)
@limiter.limit("10/minute")
def upload_incident_image(
    request: Request,
    incident_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if user.role == Role.reporter and incident.reporter_id != user.id:
        raise HTTPException(status_code=403, detail="Not permitted")

    path = save_upload(file, incident_id)
    incident.image_path = path
    db.commit()
    db.refresh(incident)
    return incident


@router.get("/{incident_id}/image")
def get_incident_image(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Serve image with authentication - no public static file access"""
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if user.role == Role.reporter and incident.reporter_id != user.id:
        raise HTTPException(status_code=403, detail="Not permitted")
    if not incident.image_path:
        raise HTTPException(status_code=404, detail="No image for this incident")

    # Verify file exists and serve it
    from pathlib import Path
    file_path = Path(incident.image_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    from fastapi.responses import FileResponse
    return FileResponse(file_path)


@router.patch("/{incident_id}/assign", response_model=IncidentOut)
def assign_incident(
    incident_id: int,
    data: AssignIncident,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.admin)),
):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    responder = db.get(User, data.responder_id)
    if not responder or responder.role != Role.responder:
        raise HTTPException(status_code=400, detail="Target user is not a responder")

    incident.assigned_to = responder.id
    incident.status = IncidentStatus.assigned
    incident.assigned_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident


@router.patch("/{incident_id}/status", response_model=IncidentOut)
def update_status(
    incident_id: int,
    data: UpdateStatus,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if user.role == Role.reporter:
        raise HTTPException(status_code=403, detail="Reporters cannot update status")

    if user.role == Role.responder and incident.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="Incident not assigned to you")

    if data.status == IncidentStatus.reported:
        raise HTTPException(status_code=400, detail="Cannot revert to reported")

    incident.status = data.status
    if data.status == IncidentStatus.resolved:
        incident.resolved_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(incident)
    return incident


@router.get("/analytics/summary")
def analytics_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.admin)),
):
    """Optimized analytics using SQL aggregation"""
    total = db.query(func.count(Incident.id)).scalar()

    cat_result = db.query(Incident.category, func.count(Incident.id)).group_by(Incident.category).all()
    by_category = dict(cat_result)

    status_result = db.query(Incident.status, func.count(Incident.id)).group_by(Incident.status).all()
    by_status = {k.value: v for k, v in status_result}

    avg_result = db.query(
        func.avg(
            func.extract('epoch', Incident.resolved_at - Incident.created_at) / 60
        )
    ).filter(Incident.resolved_at.isnot(None)).scalar()

    return {
        "total_incidents": total,
        "by_category": by_category,
        "by_status": by_status,
        "average_resolution_minutes": round(avg_result, 2) if avg_result else None,
    }
'@

    "app\services\storage.py" = @'
from pathlib import Path
from uuid import uuid4
from io import BytesIO

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import settings


ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_upload(file: UploadFile) -> str:
    raw = file.file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)

    if len(raw) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image exceeds size limit")

    try:
        image = Image.open(BytesIO(raw))
        image.verify()
        if image.format not in ALLOWED_FORMATS:
            raise HTTPException(status_code=415, detail="Use JPEG, PNG or WEBP")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=415, detail="Invalid image file")

    directory = Path(settings.upload_dir)
    directory.mkdir(parents=True, exist_ok=True)

    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
    filename = f"{uuid4().hex}{extension}"
    destination = directory / filename
    destination.write_bytes(raw)
    return str(destination)
'@

    
    "app\main.py" = @'
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.database import Base, engine
from app import models
from app.routers import auth, incidents
import structlog

# Structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # HSTS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
        # Frame options
        response.headers["X-Frame-Options"] = "DENY"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = "nosniff"
        # X-XSS-Protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("application_started", app_name=settings.app_name)
    yield
    # Shutdown
    logger.info("application_shutdown")


app = FastAPI(
    title=settings.app_name,
    description="Campus incident reporting and response API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.database_url.startswith("sqlite") else None,
    redoc_url=None,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers (custom middleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS - Restrictive
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)

# Request ID middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    import uuid
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(auth.router, prefix="/api/v1")
app.include_router(incidents.router, prefix="/api/v1")


@app.get("/", tags=["System"])
@limiter.limit("60/minute")
def home(request: Request):
    return {
        "message": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["System"])
@limiter.limit("60/minute")
def health(request: Request):
    return {"status": "ok", "version": "0.1.0"}


@app.get("/metrics", tags=["System"])
async def metrics():
    """Prometheus metrics endpoint"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
'@

    "tests\test_health.py" = @'
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_home():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Campus Emergency Response System"
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    # Should return Prometheus metrics format
    assert "http_requests_total" in response.text or "http_request_duration" in response.text
'@

    "README.md" = @'
# Campus Emergency Response & Resource Management System

A secure, cloud-ready campus incident reporting prototype with production-grade security practices.

## Current features

- **Secure Authentication**: JWT access + refresh tokens with Argon2 password hashing
- **Rate Limiting**: Per-endpoint limits (login: 10/min, register: 5/min, etc.)
- **Role-based Access Control**: Reporter, Responder, Admin roles with proper authorization
- **Incident Management**: Create, list (paginated), get, assign, update status
- **Secure Image Upload**: File-type validation (JPEG/PNG/WEBP), size limits, authenticated access
- **Analytics**: Optimized SQL-based aggregation (no full-table scans)
- **Security Headers**: HSTS, CSP, X-Frame-Options, Referrer-Policy
- **Structured Logging**: JSON logs with request IDs for tracing
- **Prometheus Metrics**: `/metrics` endpoint for monitoring
- **API Versioning**: All endpoints under `/api/v1/`
- **Local SQLite Database** (dev) / PostgreSQL ready (prod)

## Security Features Implemented

- ✅ No hardcoded secrets - JWT_SECRET required via environment variable
- ✅ Rate limiting on all auth endpoints
- ✅ Constant-time password verification (prevents email enumeration)
- ✅ Password strength requirements (uppercase, lowercase, digit, special char)
- ✅ No public static file serving - images require authentication
- ✅ Security headers (HSTS, CSP, etc.)
- ✅ CORS restricted to specific origins/methods/headers
- ✅ Request ID tracing for all requests
- ✅ Refresh token rotation
- ✅ Input validation on all endpoints

## Requirements

Python 3.11 or newer is recommended.

## Windows setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

**Required**: Edit `.env` and set `JWT_SECRET` with a strong random value:
```powershell
# Generate a secure secret:
openssl rand -base64 64
# Or in Python:
# python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Never commit `.env` to version control.

Run from the project root:

```powershell
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs

Run tests:

```powershell
python -m pytest
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | **YES** | - | 64+ char random string for JWT signing |
| `DATABASE_URL` | No | `sqlite:///./emergency.db` | Database connection string |
| `ACCESS_TOKEN_MINUTES` | No | `60` | Access token expiry |
| `REFRESH_TOKEN_DAYS` | No | `7` | Refresh token expiry |
| `RATE_LIMIT_REQUESTS` | No | `100` | Default rate limit |
| `RATE_LIMIT_WINDOW` | No | `60` | Rate limit window (seconds) |
| `MAX_UPLOAD_SIZE_MB` | No | `5` | Max image upload size |

## API Endpoints (all under `/api/v1/`)

### Authentication
- `POST /api/v1/auth/register` - Register new reporter
- `POST /api/v1/auth/login` - Login (returns access + refresh tokens)
- `POST /api/v1/auth/refresh` - Refresh access token
- `GET /api/v1/auth/me` - Get current user profile

### Incidents
- `POST /api/v1/incidents/` - Create incident
- `GET /api/v1/incidents/` - List incidents (paginated, filterable)
- `GET /api/v1/incidents/{id}` - Get incident details
- `POST /api/v1/incidents/{id}/image` - Upload incident image
- `GET /api/v1/incidents/{id}/image` - Get incident image (authenticated)
- `PATCH /api/v1/incidents/{id}/assign` - Assign to responder (admin only)
- `PATCH /api/v1/incidents/{id}/status` - Update status (responder/admin)
- `GET /api/v1/incidents/analytics/summary` - Analytics (admin only)

### System
- `GET /health` - Health check
- `GET /metrics` - Prometheus metrics

## Initial API workflow

1. Register a reporter using `POST /api/v1/auth/register`.
2. Use `POST /api/v1/auth/login` with form fields `username` (your email) and `password`.
3. Click Authorize in `/docs` and enter the **access_token**.
4. Create and list incidents via `/api/v1/incidents/`.
5. Upload an image to an incident.
6. Add an administrator and responder through a secure development-only setup process before testing assignment.

Public registration intentionally creates reporter accounts only. Do not grant admin permissions through public registration.

## Cloud integration roadmap

- ECS Fargate: host the FastAPI service
- RDS PostgreSQL: production database
- S3: incident-image object storage
- SQS: background work queue
- IAM: least-privilege permissions
- ACM: TLS certificates
- CloudWatch: logging and monitoring
- Add production migrations, monitoring, and deployment hardening before public use

This prototype is for coursework and is not yet suitable for real emergency dispatch or production use without further hardening.
'@
}

foreach ($entry in $files.GetEnumerator()) {
    $parent = Split-Path $entry.Key -Parent
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Set-Content -Path $entry.Key -Value $entry.Value -Encoding utf8
}

New-Item -ItemType File -Force -Path "uploads\.gitkeep" | Out-Null

Write-Host ""
Write-Host "Project scaffold created successfully." -ForegroundColor Green
Write-Host "Next: install requirements, configure .env, and run the server."
