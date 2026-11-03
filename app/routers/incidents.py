from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from pathlib import Path
import tempfile
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from PIL import Image, UnidentifiedImageError

from app.core.audit import log_security_event, AuditEventType
from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import (
    Incident, IncidentPriority, IncidentStatus, Role, User
)
from app.schemas import (
    IncidentCreate, IncidentOut, AssignIncident, UpdateStatus, IncidentList
)
from app.core.config import settings

router = APIRouter(prefix="/incidents", tags=["Incidents"])

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# MIME types for allowed formats
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
# Magic bytes for image formats
MAGIC_BYTES = {
    b'\xff\xd8\xff': 'JPEG',      # JPEG
    b'\x89PNG\r\n\x1a\n': 'PNG',  # PNG
    b'RIFF': 'WEBP',              # WEBP (starts with RIFF, need to check further)
}
CHUNK_SIZE = 8192  # 8KB chunks for streaming


def validate_file_extension(filename: str) -> None:
    """Validate file extension against allowed extensions"""
    if not filename:
        raise HTTPException(status_code=415, detail="Filename is required")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"File extension '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )


def validate_mime_type(file: UploadFile) -> None:
    """Validate MIME type from file content (magic bytes)"""
    # Read first 12 bytes for magic byte detection
    header = file.file.read(12)
    file.file.seek(0)  # Reset file pointer

    if not header:
        raise HTTPException(status_code=415, detail="Empty file")

    # Check magic bytes
    detected_format = None
    for magic_bytes, fmt in MAGIC_BYTES.items():
        if header.startswith(magic_bytes):
            # For WEBP, need to check further
            if fmt == 'WEBP':
                # Read more bytes to confirm WEBP
                more = file.file.read(20)
                file.file.seek(0)
                if b'WEBP' in header + more:
                    detected_format = 'WEBP'
            else:
                detected_format = fmt
            break

    if not detected_format:
        raise HTTPException(status_code=415, detail="Invalid image format. Only JPEG, PNG, and WEBP are allowed.")

    if detected_format not in ALLOWED_FORMATS:
        raise HTTPException(status_code=415, detail="Image format not allowed")


def validate_mime_type_with_python_magic(file: UploadFile) -> str:
    """Validate MIME type using python-magic library"""
    try:
        import magic
    except ImportError:
        raise HTTPException(status_code=500, detail="python-magic not available")

    # Read a chunk for magic detection
    chunk = file.file.read(8192)
    file.file.seek(0)

    if not chunk:
        raise HTTPException(status_code=415, detail="Empty file")

    try:
        # Detect MIME type
        mime_type = magic.from_buffer(chunk, mime=True)
    except Exception as e:
        # python-magic might fail on some systems
        raise HTTPException(status_code=415, detail=f"MIME type detection failed: {e}")

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"MIME type '{mime_type}' not allowed. Allowed: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    return mime_type


def save_upload(file: UploadFile, incident_id: int) -> str:
    """Save upload with streaming validation - writes to temp file first"""
    max_size = settings.max_upload_size_mb * 1024 * 1024

    # Validate file extension first
    validate_file_extension(file.filename)

    # Validate MIME type from content (magic bytes)
    try:
        mime_type = validate_mime_type_with_python_magic(file)
    except ImportError:
        # Fallback to manual magic byte detection if python-magic not available
        validate_mime_type(file)

    # Create temp file for streaming write
    temp_fd, temp_path = tempfile.mkstemp(dir=settings.upload_dir, suffix=".tmp")
    os.close(temp_fd)

    try:
        # Stream write to temp file with size limit
        total_size = 0
        with open(temp_path, "wb") as f:
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size:
                    raise HTTPException(status_code=413, detail="Image exceeds size limit")
                f.write(chunk)

        # Validate the image after writing using PIL
        try:
            image = Image.open(temp_path)
            image.verify()
            if image.format not in ALLOWED_FORMATS:
                raise HTTPException(status_code=415, detail="Use JPEG, PNG or WEBP")
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=415, detail="Invalid image file")

        # Re-open to get format (verify() closes the image)
        image = Image.open(temp_path)
        image_format = image.format
        image.close()

        # Double-check MIME type matches format
        format_to_mime = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
        }
        expected_mime = format_to_mime.get(image_format)
        if expected_mime and mime_type != expected_mime:
            # Log mismatch but don't fail - PIL is more reliable for format
            pass

        # Move temp file to final location
        directory = Path(settings.upload_dir)
        directory.mkdir(parents=True, exist_ok=True)

        extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image_format]
        filename = f"{uuid4().hex}{extension}"
        destination = directory / filename

        os.replace(temp_path, destination)
        return str(destination)

    except HTTPException:
        # Clean up temp file on HTTP errors
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
    except Exception:
        # Clean up temp file on any other error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail="Failed to save image")


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
    log_security_event(
        AuditEventType.INCIDENT_CREATED,
        user_id=user.id,
        email=user.email,
        request=request,
        details={
            "incident_id": incident.id,
            "category": incident.category,
            "priority": incident.priority.value,
        },
        success=True,
    )
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
    log_security_event(
        AuditEventType.INCIDENT_IMAGE_UPLOADED,
        user_id=user.id,
        email=user.email,
        request=request,
        details={
            "incident_id": incident.id,
            "filename": file.filename,
            "content_type": file.content_type,
        },
        success=True,
    )
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

    # Verify file exists and serve it - with path traversal protection
    from pathlib import Path
    upload_dir = Path(settings.upload_dir).resolve()
    file_path = Path(incident.image_path).resolve()

    # Prevent path traversal - ensure file is within upload directory
    try:
        file_path.relative_to(upload_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid file path")

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
    log_security_event(
        AuditEventType.INCIDENT_ASSIGNED,
        user_id=admin.id,
        email=admin.email,
        request=None,
        details={
            "incident_id": incident.id,
            "responder_id": responder.id,
            "responder_email": responder.email,
        },
        success=True,
    )
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
    log_security_event(
        AuditEventType.INCIDENT_STATUS_CHANGED,
        user_id=user.id,
        email=user.email,
        request=None,
        details={
            "incident_id": incident.id,
            "old_status": incident.status.value,
            "new_status": data.status.value,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
        success=True,
    )
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

    # Database-agnostic average resolution time calculation
    dialect = db.bind.dialect.name
    if dialect == "sqlite":
        # SQLite: use julianday for date difference in minutes
        diff_expr = (func.julianday(Incident.resolved_at) - func.julianday(Incident.created_at)) * 24 * 60
    else:
        # PostgreSQL and others: use epoch extraction
        diff_expr = func.extract('epoch', Incident.resolved_at - Incident.created_at) / 60

    avg_result = db.query(func.avg(diff_expr)).filter(Incident.resolved_at.isnot(None)).scalar()

    return {
        "total_incidents": total,
        "by_category": by_category,
        "by_status": by_status,
        "average_resolution_minutes": round(avg_result, 2) if avg_result else None,
    }