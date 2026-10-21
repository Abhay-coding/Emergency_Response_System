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
