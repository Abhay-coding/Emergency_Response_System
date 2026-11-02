from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from PIL import Image, UnidentifiedImageError

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
