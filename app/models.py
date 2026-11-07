from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Boolean, Index, Float, Integer, UniqueConstraint
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


# Password hash version constant - increment when hash algorithm/parameters change
CURRENT_PASSWORD_HASH_VERSION = 2

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    password_hash_version: Mapped[int] = mapped_column(
        default=CURRENT_PASSWORD_HASH_VERSION
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role), default=Role.reporter, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    # Track if user must reset password (e.g., due to outdated hash)
    must_reset_password: Mapped[bool] = mapped_column(default=False)

    # Token families for logout/revocation tracking
    token_families: Mapped[list["TokenFamily"]] = relationship(
        "TokenFamily", back_populates="user", cascade="all, delete-orphan"
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), index=True)
    location: Mapped[str] = mapped_column(String(200), index=True)
    priority: Mapped[IncidentPriority] = mapped_column(
        Enum(IncidentPriority), default=IncidentPriority.medium, index=True
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.reported, index=True
    )

    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    image_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TokenFamily(Base):
    """Track refresh token families per user for logout/revocation"""
    __tablename__ = "token_families"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    current_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="token_families")

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_token_families_user_revoked", "user_id", "revoked"),
        Index("ix_token_families_family_revoked", "family_id", "revoked"),
    )


class CampusPlace(Base):
    __tablename__ = "campus_places"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="building")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MedicalAlert(Base):
    __tablename__ = "medical_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(20), default="self")
    guest_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guest_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    verification: Mapped[str] = mapped_column(String(30), default="unverified")
    place_id: Mapped[int | None] = mapped_column(ForeignKey("campus_places.id"), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    callback_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    details: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    claimed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StaffContact(Base):
    __tablename__ = "staff_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(25))  # department, caretaker, warden, medical, backup
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shift: Mapped[str] = mapped_column(String(10), default="all")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PlaceCoverage(Base):
    __tablename__ = "place_coverage"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("campus_places.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_contacts.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("place_id", "staff_id"),)


class AlertAssignment(Base):
    __tablename__ = "alert_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("medical_alerts.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_contacts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    findings: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("medical_alerts.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AlertMessage(Base):
    __tablename__ = "alert_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("medical_alerts.id"), index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sender_kind: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NotificationJob(Base):
    __tablename__ = "notification_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("medical_alerts.id"), index=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_contacts.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Composite index for efficient querying of pending jobs by due date
    __table_args__ = (
        Index("ix_notification_jobs_status_due_at", "status", "due_at"),
    )
