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
