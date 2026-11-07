"""Admin-managed campus coverage and medical staff directory."""

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.database import get_db
from app.dependencies import require_roles
from app.models import CampusPlace, PlaceCoverage, Role, StaffContact, User
from app.routers.medical_alerts import seed_places

router = APIRouter(prefix="/campus", tags=["Campus medical response"])


class ContactCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    kind: Literal["department", "caretaker", "warden", "medical", "backup"]
    phone: str | None = Field(default=None, max_length=30)
    shift: Literal["day", "night", "all"] = "all"
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class ContactUpdate(BaseModel):
    phone: str | None = Field(default=None, max_length=30)
    shift: Literal["day", "night", "all"] | None = None
    active: bool | None = None


class CoverageCreate(BaseModel):
    place_id: int
    staff_id: int
    rank: int = Field(default=1, ge=1, le=100)


def contact_view(c: StaffContact) -> dict:
    return dict(id=c.id, name=c.name, kind=c.kind, phone=c.phone, shift=c.shift,
                active=c.active, user_id=c.user_id)


@router.get("/contacts")
def contacts(db: Session = Depends(get_db), admin: User = Depends(require_roles(Role.admin))):
    return [contact_view(c) for c in db.query(StaffContact).order_by(StaffContact.name).all()]


@router.post("/contacts", status_code=201)
def create_contact(data: ContactCreate, db: Session = Depends(get_db),
                   admin: User = Depends(require_roles(Role.admin))):
    if bool(data.email) != bool(data.password):
        raise HTTPException(422, "Provide both email and password for a staff login")
    user = None
    if data.email:
        if db.query(User).filter_by(email=str(data.email).lower()).first():
            raise HTTPException(409, "Email already registered")
        user = User(name=data.name, email=str(data.email).lower(),
                    password_hash=hash_password(data.password), role=Role.responder)
        db.add(user)
        db.flush()
    contact = StaffContact(name=data.name, kind=data.kind, phone=data.phone,
                           shift=data.shift, user_id=user.id if user else None)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact_view(contact)


@router.patch("/contacts/{staff_id}")
def update_contact(staff_id: int, data: ContactUpdate, db: Session = Depends(get_db),
                   admin: User = Depends(require_roles(Role.admin))):
    contact = db.get(StaffContact, staff_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    for field in ("phone", "shift", "active"):
        if field in data.model_fields_set:
            value = getattr(data, field)
            if field != "phone" and value is None:
                raise HTTPException(422, f"{field} cannot be null")
            setattr(contact, field, value)
    db.commit()
    return contact_view(contact)


@router.post("/coverage", status_code=201)
def set_coverage(data: CoverageCreate, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles(Role.admin))):
    if not db.get(CampusPlace, data.place_id) or not db.get(StaffContact, data.staff_id):
        raise HTTPException(404, "Place or contact not found")
    row = db.query(PlaceCoverage).filter_by(place_id=data.place_id, staff_id=data.staff_id).first()
    if row:
        row.rank = data.rank
    else:
        row = PlaceCoverage(**data.model_dump())
        db.add(row)
    db.commit()
    return {"place_id": row.place_id, "staff_id": row.staff_id, "rank": row.rank}


@router.get("/coverage/{place_id}")
def coverage(place_id: int, db: Session = Depends(get_db),
             admin: User = Depends(require_roles(Role.admin))):
    seed_places(db)
    if not db.get(CampusPlace, place_id):
        raise HTTPException(404, "Place not found")
    rows = db.query(PlaceCoverage, StaffContact).join(
        StaffContact, StaffContact.id == PlaceCoverage.staff_id
    ).filter(PlaceCoverage.place_id == place_id, StaffContact.active.is_(True)).order_by(
        PlaceCoverage.rank, StaffContact.name
    ).all()
    hour = datetime.now(ZoneInfo(settings.campus_timezone)).hour
    current_shift = "day" if 6 <= hour < 18 else "night"
    return [dict(**contact_view(c), rank=r.rank, on_duty=c.shift in ("all", current_shift))
            for r, c in rows]


@router.get("/operations")
def operations(db: Session = Depends(get_db), admin: User = Depends(require_roles(Role.admin))):
    from app.models import NotificationJob
    failed = db.query(NotificationJob).filter_by(status="failed").count()
    return {
        "notification_mode": settings.notification_mode,
        "sqs_configured": bool(settings.aws_sqs_queue_url),
        "backup_configured": bool(settings.backup_phone),
        "campus_emergency_phone_configured": bool(settings.campus_emergency_phone),
        "failed_jobs": failed,
        "live_ready": settings.notification_mode == "sns" and bool(
            settings.backup_phone and settings.campus_emergency_phone
        ),
    }
