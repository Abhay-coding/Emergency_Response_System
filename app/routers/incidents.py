from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

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
from app.services.storage import save_upload

router = APIRouter(prefix="/incidents", tags=["Incidents"])


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
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Incident)
    if user.role == Role.reporter:
        query = query.filter(Incident.reporter_id == user.id)
    elif user.role == Role.responder:
        query = query.filter(Incident.assigned_to == user.id)
    if status:
        query = query.filter(Incident.status == status)
    if priority:
        query = query.filter(Incident.priority == priority)
    if category:
        query = query.filter(Incident.category == category)

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
    if (user.role == Role.reporter and incident.reporter_id != user.id) or (user.role == Role.responder and incident.assigned_to != user.id):
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
    if (user.role == Role.reporter and incident.reporter_id != user.id) or (user.role == Role.responder and incident.assigned_to != user.id):
        raise HTTPException(status_code=403, detail="Not permitted")

    path = save_upload(file, prefix=f"incident_{incident_id}_")
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
    if (user.role == Role.reporter and incident.reporter_id != user.id) or (user.role == Role.responder and incident.assigned_to != user.id):
        raise HTTPException(status_code=403, detail="Not permitted")
    if not incident.image_path:
        raise HTTPException(status_code=404, detail="No image for this incident")

    # Verify file exists and serve it - with path traversal protection
    from pathlib import Path
    import os

    upload_dir = Path(settings.upload_dir).resolve()

    # Get the file path without resolving symlinks
    file_path = Path(incident.image_path)

    # Check if path is a symlink or contains symlinks
    # We need to resolve to check, but we should reject symlinks
    try:
        # Check if the path itself is a symlink
        if file_path.is_symlink():
            raise HTTPException(status_code=403, detail="Symlinks not allowed")

        # Also check if any parent directory is a symlink
        for parent in file_path.parents:
            if parent.is_symlink():
                raise HTTPException(status_code=403, detail="Symlinks in path not allowed")

        # Now resolve the path safely (no symlinks in path)
        file_path = file_path.resolve()

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid file path")

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
@limiter.limit("20/minute")
def assign_incident(
    request: Request,
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

    old_status = incident.status.value
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
            "old_status": old_status,
            "new_status": data.status.value,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
        success=True,
    )
    return incident


@router.get("/analytics/summary")
@limiter.limit("20/minute")
def analytics_summary(
    request: Request,
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
