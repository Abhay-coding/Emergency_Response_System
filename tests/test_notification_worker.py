from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import MedicalAlert, NotificationJob, utc_now
from app.core.config import settings
from app.services.notifications import process_due_jobs


def test_acknowledged_alert_cancels_backup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        alert = MedicalAlert(source="self", idempotency_key="worker-acknowledged",
                             status="acknowledged", acknowledged_at=utc_now())
        db.add(alert)
        db.flush()
        job = NotificationJob(alert_id=alert.id, kind="backup_escalation",
                              due_at=utc_now() - timedelta(seconds=1))
        db.add(job)
        db.commit()
        assert process_due_jobs(db) == 1
        db.refresh(job)
        assert job.status == "cancelled"


def test_missing_backup_is_visible_failure(monkeypatch):
    monkeypatch.setattr(settings, "notification_mode", "sns")
    monkeypatch.setattr(settings, "backup_phone", None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        alert = MedicalAlert(source="self", idempotency_key="worker-missing-backup")
        db.add(alert)
        db.flush()
        job = NotificationJob(alert_id=alert.id, kind="backup_escalation",
                              due_at=utc_now() - timedelta(seconds=1))
        db.add(job)
        db.commit()
        assert process_due_jobs(db) == 1
        db.refresh(job)
        assert job.status == "failed"
        assert "backup" in job.last_error.lower()


def test_simulation_never_claims_delivery(monkeypatch):
    monkeypatch.setattr(settings, "notification_mode", "simulation")
    monkeypatch.setattr(settings, "backup_phone", "+911234567890")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        alert = MedicalAlert(source="self", idempotency_key="worker-simulation")
        db.add(alert)
        db.flush()
        job = NotificationJob(alert_id=alert.id, kind="backup_escalation",
                              due_at=utc_now() - timedelta(seconds=1))
        db.add(job)
        db.commit()
        assert process_due_jobs(db) == 1
        assert process_due_jobs(db) == 0
        db.refresh(job)
        assert job.status == "simulated"
        assert job.sent_at is None
