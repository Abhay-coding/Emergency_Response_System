from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Boolean, Index
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
        Enum(Role), default=Role.reporter, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )

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