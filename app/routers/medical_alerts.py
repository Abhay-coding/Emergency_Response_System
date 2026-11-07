"""Medical-only, human-operated campus alert workflow."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import new as hmac_new, compare_digest
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.constants import GUEST_TOKEN_EXPIRY_DAYS
from app.database import get_db
from app.dependencies import get_optional_user, require_roles
from app.models import (
    AlertAssignment, AlertEvent, AlertMessage, CampusPlace, MedicalAlert,
    NotificationJob, PlaceCoverage, Role, StaffContact, User, utc_now,
)
from app.schemas import validate_no_xss
from app.services.notifications import queue_job
from app.data_api_repository import DataAPIRepository, get_repo

router = APIRouter(prefix="/medical-alerts", tags=["Medical alerts"])

PLACE_NAMES = [
    ("CSED Lab", "building"), ("Library", "building"),
    ("C Block", "building"), ("B Block", "building"),
    ("F Block", "building"), ("G Block", "building"),
    ("Main Gate", "gate"),
    ("A Hostel", "hostel"), ("O Hostel", "hostel"),
    ("B Hostel", "hostel"), ("C Hostel", "hostel"),
    ("D Hostel", "hostel"),
    ("G Girls Hostel", "hostel"), ("N Girls Hostel", "hostel"),
    ("Q Girls Hostel", "hostel"), ("PG1 Girls Hostel", "hostel"),
    ("PG2 Girls Hostel", "hostel"),
    ("Electrical Department", "department"),
    ("Computer Department", "department"),
    ("Electronics Department", "department"),
]


def seed_places(db: Session) -> None:
    if db.query(CampusPlace.id).first():
        return
    db.add_all(CampusPlace(name=name, kind=kind) for name, kind in PLACE_NAMES)
    db.commit()


def token_for_key(key: str) -> str:
    # The client-generated idempotency key is never returned in admin views.
    # Use guest_token_secret if configured, otherwise fall back to jwt_secret for backward compatibility
    secret = settings.guest_token_secret or settings.jwt_secret
    return hmac_new(secret.encode(), f"guest:{key}".encode(), "sha256").hexdigest()


def guest_access(alert: MedicalAlert, token: str | None) -> bool:
    expires = alert.guest_token_expires_at
    if not expires or expires.replace(tzinfo=timezone.utc) <= utc_now():
        return False
    if not alert.guest_token_hash or not token:
        return False
    # Compute hash first to avoid timing attack on hash computation
    token_hash = sha256(token.encode()).hexdigest()
    return compare_digest(alert.guest_token_hash, token_hash)


def access_or_403(alert: MedicalAlert, user: User | None, token: str | None) -> None:
    if user and (user.role == Role.admin or alert.reporter_id == user.id):
        return
    if guest_access(alert, token):
        return
    raise HTTPException(403, "Not permitted")


def event(db: Session, alert_id: int, action: str, actor_id: int | None = None,
          note: str | None = None) -> None:
    db.add(AlertEvent(alert_id=alert_id, actor_id=actor_id, action=action, note=note))


def alert_view(alert: MedicalAlert, *, limited: bool = False) -> dict:
    data = {
        "id": alert.id, "source": alert.source, "status": alert.status,
        "identity_verified": alert.reporter_id is not None,
        "place_id": alert.place_id, "location_text": alert.location_text,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
    }
    if not limited:
        data.update(
            reporter_id=alert.reporter_id, callback_phone=alert.callback_phone,
            details=alert.details, verification=alert.verification,
            claimed_by=alert.claimed_by, latitude=alert.latitude,
            longitude=alert.longitude, accuracy_m=alert.accuracy_m,
        )
    return data


class AlertCreate(BaseModel):
    source: Literal["self", "bystander"] = "self"


class LocationUpdate(BaseModel):
    place_name: str | None = Field(default=None, max_length=100)
    location_text: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    callback_phone: str | None = Field(default=None, max_length=30)
    details: str | None = Field(default=None, max_length=1000)

    @field_validator('place_name', 'location_text', 'callback_phone', 'details')
    @classmethod
    def validate_no_xss_fields(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_no_xss(v, 'location_update')
        return v


class StaffAlert(BaseModel):
    user_id: int | None = None
    staff_id: int | None = None


class StaffFindings(BaseModel):
    findings: str = Field(min_length=2, max_length=1000)


class ActionNote(BaseModel):
    note: str = Field(min_length=2, max_length=1000)


class FalseReport(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


@router.get("/places")
def places(db: Session = Depends(get_db)):
    return [dict(id=p.id, name=p.name, kind=p.kind) for p in
            db.query(CampusPlace).filter(CampusPlace.active.is_(True)).order_by(CampusPlace.name).all()]


@router.get("/config")
def public_config():
    return {"campus_emergency_phone": settings.campus_emergency_phone,
            "prototype": settings.notification_mode != "sns"}


@router.post("", status_code=201)
@limiter.limit("10/minute")
def create_alert(request: Request, data: AlertCreate,
                 idempotency_key: str = Header(..., alias="Idempotency-Key"),
                 db: Session = Depends(get_db), user: User | None = Depends(get_optional_user),
                 repo: DataAPIRepository | None = Depends(lambda: get_repo() if settings.data_api_enabled else None)):
    try:
        parsed_key = UUID(idempotency_key)
        # Accept any valid UUID version, not just v4
        idempotency_key = str(parsed_key)
    except ValueError:
        raise HTTPException(422, "Idempotency-Key must be a valid UUID")
    if repo:
        tx = repo.begin_transaction()
        try:
            inserted = repo.execute(
                "INSERT INTO medical_alerts (idempotency_key, source, reporter_id, status, verification, created_at, updated_at) VALUES (:key, :source, :reporter_id, 'new', 'unverified', NOW(), NOW()) RETURNING id",
                [{"name":"key","value":{"stringValue":idempotency_key}}, {"name":"source","value":{"stringValue":data.source}}, {"name":"reporter_id","value":{"isNull": user is None, **({"longValue":user.id} if user else {})}}], tx)
            alert_id = inserted["records"][0][0]["longValue"]
            repo.execute("INSERT INTO alert_events (alert_id, actor_id, action, created_at) VALUES (:alert_id, :actor_id, 'created', NOW())", [{"name":"alert_id","value":{"longValue":alert_id}}, {"name":"actor_id","value":{"isNull": user is None, **({"longValue":user.id} if user else {})}}], tx)
            repo.commit(tx)
            return {"id": alert_id, "status": "new", "identity_verified": bool(user), "guest_token": None}
        except Exception as exc:
            repo.rollback(tx)
            raise HTTPException(503, "Unable to record medical alert") from exc
    existing = db.query(MedicalAlert).filter_by(idempotency_key=idempotency_key).first()
    if existing:
        if existing.reporter_id != (user.id if user else None):
            raise HTTPException(409, "Request key already used")
        result = alert_view(existing, limited=True)
        if not user and guest_access(existing, token_for_key(idempotency_key)):
            result["guest_token"] = token_for_key(idempotency_key)
        return result
    guest_token = token_for_key(idempotency_key) if not user else None
    alert = MedicalAlert(
        source=data.source, reporter_id=user.id if user else None,
        guest_token_hash=sha256(guest_token.encode()).hexdigest() if guest_token else None,
        guest_token_expires_at=utc_now() + timedelta(days=GUEST_TOKEN_EXPIRY_DAYS) if guest_token else None,
        idempotency_key=idempotency_key,
    )
    db.add(alert)
    try:
        db.flush()
        event(db, alert.id, "created", user.id if user else None)
        job = NotificationJob(alert_id=alert.id, kind="backup_escalation",
                              due_at=utc_now() + timedelta(seconds=settings.alert_ack_seconds))
        db.add(job)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Request key already used")
    db.refresh(alert)
    queue_job(job)
    result = alert_view(alert, limited=True)
    if guest_token:
        result["guest_token"] = guest_token
    return result


@router.get("/mine")
def my_alerts(db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    if not user:
        raise HTTPException(401, "Sign in required")
    return [alert_view(a, limited=True) for a in db.query(MedicalAlert)
            .filter_by(reporter_id=user.id).order_by(MedicalAlert.created_at.desc()).limit(30).all()]


@router.get("/admin/queue")
@limiter.limit("30/minute")
def admin_queue(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_roles(Role.admin))):
    alerts = db.query(MedicalAlert).order_by(MedicalAlert.created_at.desc()).limit(100).all()
    return [alert_view(a) for a in alerts]


@router.get("/staff/inbox")
@limiter.limit("30/minute")
def staff_inbox(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.responder))):
    """Get staff inbox with single query using subquery to avoid N+1"""
    # Subquery to get latest assignment per alert for this user
    from sqlalchemy import func
    latest_assignment_subq = (
        db.query(
            AlertAssignment.alert_id,
            func.max(AlertAssignment.id).label("max_id")
        )
        .filter(AlertAssignment.user_id == user.id)
        .group_by(AlertAssignment.alert_id)
        .subquery()
    )

    # Join with MedicalAlert and AlertAssignment in single query
    results = (
        db.query(MedicalAlert, AlertAssignment)
        .join(
            latest_assignment_subq,
            (MedicalAlert.id == latest_assignment_subq.c.alert_id)
        )
        .join(
            AlertAssignment,
            (AlertAssignment.id == latest_assignment_subq.c.max_id)
        )
        .order_by(MedicalAlert.created_at.desc())
        .all()
    )

    return [
        dict(alert_view(alert), assignment_status=assignment.status)
        for alert, assignment in results
    ]


@router.get("/{alert_id}/public")
def public_status(alert_id: int, x_alert_token: str | None = Header(default=None, alias="X-Alert-Token"),
                  db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    alert = db.get(MedicalAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    access_or_403(alert, user, x_alert_token)
    return alert_view(alert, limited=True)


@router.patch("/{alert_id}/location")
def update_location(alert_id: int, data: LocationUpdate,
                    x_alert_token: str | None = Header(default=None, alias="X-Alert-Token"),
                    db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    alert = db.get(MedicalAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    access_or_403(alert, user, x_alert_token)
    if data.place_name:
        place = db.query(CampusPlace).filter(CampusPlace.name == data.place_name,
                                            CampusPlace.active.is_(True)).first()
        if not place:
            raise HTTPException(422, "Unknown campus place")
        alert.place_id = place.id

    # Explicit field mapping to prevent SQL injection via setattr with user-controlled field names
    allowed_fields = {
        "location_text": data.location_text,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "accuracy_m": data.accuracy_m,
        "callback_phone": data.callback_phone,
        "details": data.details,
    }

    for field, value in allowed_fields.items():
        if field in data.model_fields_set and value is not None:
            setattr(alert, field, value)
    event(db, alert.id, "details_updated", user.id if user else None)
    db.commit()
    db.refresh(alert)
    return alert_view(alert, limited=True)


@router.post("/{alert_id}/claim")
@limiter.limit("20/minute")
def claim_alert(request: Request, alert_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    now = utc_now()
    result = db.execute(update(MedicalAlert).where(
        MedicalAlert.id == alert_id, MedicalAlert.claimed_by.is_(None)
    ).values(claimed_by=admin.id, acknowledged_at=now, status="acknowledged"))
    if not result.rowcount:
        alert = db.get(MedicalAlert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")
        if alert.claimed_by != admin.id:
            raise HTTPException(409, "Another admin has claimed this alert")
    else:
        event(db, alert_id, "claimed", admin.id)
    db.commit()
    return alert_view(db.get(MedicalAlert, alert_id))


def admin_alert(db: Session, alert_id: int) -> MedicalAlert:
    alert = db.get(MedicalAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return alert


@router.post("/{alert_id}/contact")
@limiter.limit("20/minute")
def record_contact(request: Request, alert_id: int, data: ActionNote, db: Session = Depends(get_db),
                   admin: User = Depends(require_roles(Role.admin))):
    alert = admin_alert(db, alert_id)
    alert.status = "checking"
    event(db, alert.id, "contact_attempt", admin.id, data.note)
    db.commit()
    return alert_view(alert)


@router.post("/{alert_id}/verify")
@limiter.limit("20/minute")
def verify_need(request: Request, alert_id: int, data: ActionNote, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    alert = admin_alert(db, alert_id)
    alert.verification = "confirmed_need"
    event(db, alert.id, "need_confirmed", admin.id, data.note)
    db.commit()
    return alert_view(alert)


@router.post("/{alert_id}/staff")
@limiter.limit("10/minute")
def alert_staff(request: Request, alert_id: int, data: StaffAlert, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    alert = admin_alert(db, alert_id)
    if not alert.claimed_by:
        raise HTTPException(409, "Admin must review and claim the alert first")
    contact = db.get(StaffContact, data.staff_id) if data.staff_id else None
    if contact and not contact.active:
        raise HTTPException(422, "Staff contact inactive")
    if contact and contact.kind in {"caretaker", "warden"} and alert.status == "acknowledged":
        raise HTTPException(409, "Record admin review before notifying hostel staff")
    user_id = data.user_id or (contact.user_id if contact else None)
    if not user_id and not contact:
        raise HTTPException(422, "Choose a staff account or contact")
    if user_id:
        staff_user = db.get(User, user_id)
        if not staff_user or staff_user.role != Role.responder:
            raise HTTPException(422, "Target account is not staff")
    assignment = AlertAssignment(alert_id=alert_id, user_id=user_id,
                                 staff_id=contact.id if contact else None)
    db.add(assignment)
    db.flush()
    job = None
    if contact and contact.phone:
        job = NotificationJob(alert_id=alert_id, staff_id=contact.id,
                              kind="staff_alert", due_at=utc_now())
        db.add(job)
    alert.status = "staff_alerted"
    event(db, alert.id, "staff_alerted", admin.id,
          f"Staff assignment #{assignment.id}")
    db.commit()
    if job:
        queue_job(job)
    return {"assignment_id": assignment.id, "status": assignment.status}


@router.post("/{alert_id}/staff/acknowledge")
def acknowledge_staff(alert_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(Role.responder))):
    assignment = db.query(AlertAssignment).filter_by(alert_id=alert_id, user_id=user.id).order_by(
        AlertAssignment.id.desc()).first()
    if not assignment:
        raise HTTPException(403, "Alert not assigned to you")
    assignment.status = "acknowledged"
    assignment.acknowledged_at = utc_now()
    event(db, alert_id, "staff_acknowledged", user.id)
    db.commit()
    return {"status": assignment.status}


@router.post("/{alert_id}/staff/findings")
def staff_findings(alert_id: int, data: StaffFindings, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(Role.responder))):
    assignment = db.query(AlertAssignment).filter_by(alert_id=alert_id, user_id=user.id).order_by(
        AlertAssignment.id.desc()).first()
    if not assignment:
        raise HTTPException(403, "Alert not assigned to you")
    assignment.findings = data.findings
    event(db, alert_id, "staff_findings", user.id, data.findings)
    db.commit()
    return {"status": "recorded"}


@router.post("/{alert_id}/dispatch-medical")
@limiter.limit("10/minute")
def dispatch_medical(request: Request, alert_id: int, data: ActionNote, db: Session = Depends(get_db),
                     admin: User = Depends(require_roles(Role.admin))):
    alert = admin_alert(db, alert_id)
    alert.status = "medical_dispatched"
    event(db, alert.id, "medical_dispatched", admin.id, data.note)
    db.commit()
    return alert_view(alert)


@router.post("/{alert_id}/resolve")
@limiter.limit("10/minute")
def resolve_alert(request: Request, alert_id: int, data: ActionNote, db: Session = Depends(get_db),
                  admin: User = Depends(require_roles(Role.admin))):
    alert = admin_alert(db, alert_id)
    alert.status = "resolved"
    alert.closed_at = utc_now()
    event(db, alert.id, "resolved", admin.id, data.note)
    db.commit()
    return alert_view(alert)


@router.post("/{alert_id}/close-false")
@limiter.limit("10/minute")
def close_false(request: Request, alert_id: int, data: FalseReport, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    alert = admin_alert(db, alert_id)
    if not alert.claimed_by:
        raise HTTPException(409, "Review the alert before closing it")
    alert.status = "closed_false_report"
    alert.verification = "confirmed_false"
    alert.closed_at = utc_now()
    event(db, alert.id, "closed_false_report", admin.id, data.reason)
    db.commit()
    return alert_view(alert)


@router.get("/{alert_id}/events")
@limiter.limit("30/minute")
def alert_events(request: Request, alert_id: int, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles(Role.admin))):
    admin_alert(db, alert_id)
    return [dict(action=e.action, note=e.note, actor_id=e.actor_id,
                 created_at=e.created_at.isoformat()) for e in
            db.query(AlertEvent).filter_by(alert_id=alert_id).order_by(AlertEvent.id).all()]


@router.get("/{alert_id}/messages")
@limiter.limit("30/minute")
def messages(request: Request, alert_id: int, x_alert_token: str | None = Header(default=None, alias="X-Alert-Token"),
             db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    alert = admin_alert(db, alert_id)
    access_or_403(alert, user, x_alert_token)
    return [dict(sender_kind=m.sender_kind, body=m.body, created_at=m.created_at.isoformat())
            for m in db.query(AlertMessage).filter_by(alert_id=alert_id).order_by(AlertMessage.id).all()]


@router.post("/{alert_id}/messages")
@limiter.limit("20/minute")
def send_message(request: Request, alert_id: int, data: MessageIn,
                 x_alert_token: str | None = Header(default=None, alias="X-Alert-Token"),
                 db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    alert = admin_alert(db, alert_id)
    access_or_403(alert, user, x_alert_token)
    kind = "admin" if user and user.role == Role.admin else "student"
    db.add(AlertMessage(alert_id=alert_id, sender_id=user.id if user else None,
                        sender_kind=kind, body=data.body))
    event(db, alert_id, "message_sent", user.id if user else None)
    db.commit()
    return {"status": "sent"}
