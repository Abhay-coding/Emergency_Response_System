
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
JWT_SECRET=replace-this-with-a-long-random-secret
ACCESS_TOKEN_MINUTES=60
'@

    "app\core\config.py" = @'
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Campus Emergency Response System"
    database_url: str = "sqlite:///./emergency.db"
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 5
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
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
    password: str = Field(min_length=8, max_length=128)


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
    token_type: str = "bearer"


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
        {"sub": subject, "exp": expiry},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],
    )
'@

    "app\dependencies.py" = @'
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt

from app.core.security import decode_access_token
from app.database import get_db
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


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
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token, hash_password, verify_password
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Role, User
from app.schemas import TokenOut, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    if db.query(User).filter(User.email == email).first():
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
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return TokenOut(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
'@

    "app\routers\incidents.py" = @'
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import (
    Incident, IncidentPriority, IncidentStatus, Role, User
)
from app.schemas import (
    IncidentCreate, IncidentOut, AssignIncident, UpdateStatus
)
from app.services.storage import save_upload

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post("", response_model=IncidentOut, status_code=201)
def create_incident(
    data: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = Incident(**data.model_dump(), reporter_id=user.id)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Incident)
    if user.role == Role.reporter:
        query = query.filter(Incident.reporter_id == user.id)
    return query.order_by(Incident.created_at.desc()).all()


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
def upload_incident_image(
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

    path = save_upload(file)
    incident.image_path = path
    db.commit()
    db.refresh(incident)
    return incident


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
    incidents = db.query(Incident).all()
    response_times = [
        (i.resolved_at - i.created_at).total_seconds() / 60
        for i in incidents
        if i.resolved_at and i.created_at
    ]
    return {
        "total_incidents": len(incidents),
        "by_category": _count_by(incidents, "category"),
        "by_status": _count_by(incidents, "status"),
        "average_resolution_minutes": (
            round(sum(response_times) / len(response_times), 2)
            if response_times else None
        ),
    }


def _count_by(incidents, field):
    counts = {}
    for incident in incidents:
        value = getattr(incident, field)
        value = value.value if hasattr(value, "value") else value
        counts[value] = counts.get(value, 0) + 1
    return counts
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
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.database import Base, engine
from app import models
from app.routers import auth, incidents

Base.metadata.create_all(bind=engine)

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title=settings.app_name,
    description="Campus incident reporting and response API",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(incidents.router)

app.mount(
    "/uploads",
    StaticFiles(directory=settings.upload_dir),
    name="uploads",
)


@app.get("/", tags=["System"])
def home():
    return {
        "message": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}
'@

    "tests\test_health.py" = @'
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"
'@

    "README.md" = @'
# Campus Emergency Response & Resource Management System

A cloud-ready campus incident reporting prototype.

## Current features

- Reporter registration and JWT login
- Role-aware API access
- Incident creation and listing
- Incident image upload with file-type and size checks
- Administrator assignment endpoint
- Responder status updates
- Incident analytics endpoint
- Local SQLite database
- FastAPI interactive documentation

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

Before using this beyond local development, replace `JWT_SECRET` in `.env` with a long random secret. Never commit `.env`.

Run from the project root:

```powershell
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs

Run tests:

```powershell
python -m pytest
```

## Initial API workflow

1. Register a reporter using `POST /auth/register`.
2. Use `POST /auth/login` with form fields `username` (your email) and `password`.
3. Click Authorize in `/docs` and enter the returned token.
4. Create and list incidents.
5. Upload an image to an incident.
6. Add an administrator and responder through a secure development-only setup process before testing assignment.

Public registration intentionally creates reporter accounts only. Do not grant admin permissions through public registration.

## Cloud integration roadmap

- EC2: host the FastAPI service
- S3: incident-image object storage
- SQS: background work queue
- DynamoDB: cloud incident records
- IAM: least-privilege permissions
- Add production migrations, monitoring, and deployment hardening before public use

This prototype is for coursework and is not yet suitable for real emergency dispatch or production use.
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
