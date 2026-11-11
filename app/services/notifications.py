"""Durable outbound notification processing.

The database is the source of truth so an ECS worker can resume jobs after
restart. A message sent through SNS is marked sent only after SNS accepts it.
"""

import logging
import json
import time
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from app.core.config import settings
from app.core.constants import (
    WORKER_SQS_WAIT_TIME_SECONDS,
    WORKER_SQS_MAX_MESSAGES,
    WORKER_MAX_RETRIES,
    WORKER_RETRY_BASE_DELAY_SECONDS,
)
from app.database import get_for_update_clause
from app.models import MedicalAlert, NotificationJob, StaffContact, utc_now

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Base exception for notification errors."""
    pass


class ConfigurationError(NotificationError):
    """Raised when notification configuration is missing."""
    pass


class DeliveryError(NotificationError):
    """Raised when notification delivery fails."""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _alert_on_failure(alert_id: int, error: str, context: dict) -> None:
    """Log critical failure for alerting systems to pick up.

    In production, this could integrate with CloudWatch, PagerDuty, etc.
    """
    logger.critical(
        "notification_critical_failure",
        extra={
            "alert_id": alert_id,
            "error": error,
            "context": context,
            "requires_attention": True,
        }
    )


def queue_job(job: NotificationJob) -> None:
    """Wake the cloud worker; the DB job remains authoritative if SQS is unavailable."""
    if not settings.aws_sqs_queue_url:
        logger.debug("sqs_not_configured", extra={"job_id": job.id})
        return

    start_time = time.time()
    try:
        import boto3
        delay = max(0, min(900, int((job.due_at.replace(tzinfo=None) - utc_now().replace(tzinfo=None)).total_seconds())))
        boto3.client("sqs", region_name=settings.aws_region).send_message(
            QueueUrl=settings.aws_sqs_queue_url,
            MessageBody=json.dumps({"job_id": job.id}),
            DelaySeconds=delay,
        )
        duration_ms = (time.time() - start_time) * 1000
        logger.debug(
            "sqs_wakeup_queued",
            extra={"job_id": job.id, "delay_seconds": delay, "duration_ms": round(duration_ms, 2)}
        )
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.exception(
            "sqs_wakeup_failed",
            extra={"job_id": job.id, "duration_ms": round(duration_ms, 2), "error_type": type(exc).__name__}
        )


def receive_wakeups() -> int:
    """Receive and delete wakeup messages using long-polling.

    Returns the number of messages processed.
    """
    if not settings.aws_sqs_queue_url:
        return 0

    import boto3
    client = boto3.client("sqs", region_name=settings.aws_region)

    start_time = time.time()
    try:
        response = client.receive_message(
            QueueUrl=settings.aws_sqs_queue_url,
            MaxNumberOfMessages=WORKER_SQS_MAX_MESSAGES,
            WaitTimeSeconds=WORKER_SQS_WAIT_TIME_SECONDS,
            VisibilityTimeout=30,
        )
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.exception(
            "sqs_receive_failed",
            extra={"duration_ms": round(duration_ms, 2), "error_type": type(exc).__name__}
        )
        return 0

    duration_ms = (time.time() - start_time) * 1000
    # A wakeup is only a hint. The DB poll below always checks due jobs.
    messages = response.get("Messages", [])
    count = 0
    for message in messages:
        try:
            client.delete_message(
                QueueUrl=settings.aws_sqs_queue_url,
                ReceiptHandle=message["ReceiptHandle"]
            )
            count += 1
        except Exception:
            logger.exception("sqs_delete_failed", extra={"message_id": message.get("MessageId")})

    if count > 0:
        logger.debug(
            "sqs_wakeups_received",
            extra={"count": count, "duration_ms": round(duration_ms, 2)}
        )

    return count


def _phone_for_job(db: Session, job: NotificationJob) -> str:
    """Get the phone number for a notification job."""
    if job.kind == "backup_escalation":
        if not settings.backup_phone:
            raise ConfigurationError("Backup phone is not configured")
        return settings.backup_phone

    contact = db.get(StaffContact, job.staff_id) if job.staff_id else None
    if not contact or not contact.phone:
        raise ConfigurationError("Staff phone is not configured")
    return contact.phone


def _send(phone: str, alert_id: int, kind: str) -> None:
    """Send notification via SNS."""
    if settings.dynamo_demo_enabled:
        raise ConfigurationError("Real outbound notifications are disabled in demo mode")
    if settings.notification_mode != "sns":
        raise ConfigurationError("Outbound notification provider is not configured")

    start_time = time.time()
    try:
        import boto3
        client = boto3.client("sns", region_name=settings.aws_region)
        # Avoid medical details in SMS, logs, and AWS delivery records.
        client.publish(
            PhoneNumber=phone,
            Message=f"Campus medical assistance alert #{alert_id}. Open the staff portal or contact the campus admin now.",
            MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}},
        )
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "notification_sent",
            extra={"alert_id": alert_id, "kind": kind, "duration_ms": round(duration_ms, 2)}
        )
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.exception(
            "notification_send_failed",
            extra={
                "alert_id": alert_id,
                "kind": kind,
                "duration_ms": round(duration_ms, 2),
                "error_type": type(exc).__name__
            }
        )
        raise DeliveryError(f"Failed to send notification: {exc}") from exc


def _update_job_status(
    db: Session,
    job: NotificationJob,
    status: str,
    error: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> None:
    """Update job status with proper error handling."""
    try:
        job.status = status
        job.last_error = error
        if sent_at:
            job.sent_at = sent_at
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "job_status_update_failed",
            extra={"job_id": job.id, "status": status, "error_type": type(exc).__name__}
        )
        raise


def process_due_jobs(db: Session, limit: int = 25) -> int:
    """Process due jobs. Multiple workers recheck state before sending.

    For PostgreSQL, uses FOR UPDATE SKIP LOCKED for row-level locking.
    For SQLite, uses UPDATE-then-SELECT pattern to atomically claim jobs.
    """
    from datetime import datetime
    from app.database import get_dialect, DatabaseDialect
    now = utc_now()
    dialect = get_dialect()

    if dialect == DatabaseDialect.SQLITE:
        # SQLite doesn't support FOR UPDATE SKIP LOCKED
        # Use UPDATE-then-SELECT pattern to atomically claim jobs
        from sqlalchemy import update as sqlalchemy_update

        # Claim each candidate conditionally. This works on older SQLite
        # versions without RETURNING and records exactly what this worker won.
        due_ids = (db.query(NotificationJob.id).filter(
            NotificationJob.status == "pending", NotificationJob.due_at <= now
        ).order_by(NotificationJob.due_at, NotificationJob.id).limit(limit).all())
        claimed_ids=[]
        for (job_id,) in due_ids:
            result=db.execute(sqlalchemy_update(NotificationJob).where(
                NotificationJob.id == job_id, NotificationJob.status == "pending"
            ).values(status="processing"))
            if result.rowcount: claimed_ids.append(job_id)
        if not claimed_ids:
            return 0
        jobs = db.query(NotificationJob).filter(NotificationJob.id.in_(claimed_ids)).order_by(NotificationJob.due_at, NotificationJob.id).all()
    else:
        # PostgreSQL/MySQL: use FOR UPDATE SKIP LOCKED
        # Also join with MedicalAlert to atomically check alert status
        for_update_options = get_for_update_clause(skip_locked=True)
        query = (db.query(NotificationJob)
                .join(MedicalAlert, NotificationJob.alert_id == MedicalAlert.id)
                .filter(
                    NotificationJob.status == "pending",
                    NotificationJob.due_at <= now,
                    MedicalAlert.closed_at.is_(None),
                    # Exclude backup_escalation jobs for acknowledged alerts
                    (NotificationJob.kind != "backup_escalation") | (MedicalAlert.acknowledged_at.is_(None))
                )
                .order_by(NotificationJob.due_at, NotificationJob.id))

        if for_update_options:
            query = query.with_for_update(**for_update_options)

        jobs = query.limit(limit).all()

    count = 0
    processed_count = 0
    failed_count = 0

    for job in jobs:
        count += 1
        # Alert status already verified in query, no need to re-fetch
        alert = db.get(MedicalAlert, job.alert_id)

        try:
            if not alert or alert.closed_at is not None or (job.kind == "backup_escalation" and alert.acknowledged_at is not None):
                _update_job_status(db, job, "cancelled")
                continue
            phone = _phone_for_job(db, job)

            if settings.notification_mode == "simulation":
                job.status = "simulated"
                _update_job_status(db, job, "simulated")
                processed_count += 1
                logger.info("notification_simulated", extra={"alert_id": alert.id, "kind": job.kind})
            else:
                _send(phone, alert.id, job.kind)
                _update_job_status(db, job, "sent", sent_at=utc_now())
                processed_count += 1

        except ConfigurationError as exc:
            # Configuration errors are not retryable - mark as failed immediately
            _update_job_status(db, job, "failed", error=str(exc))
            failed_count += 1
            _alert_on_failure(alert.id, str(exc), {"job_id": job.id, "kind": job.kind, "error_type": "configuration"})

        except DeliveryError as exc:
            job.attempts += 1
            if job.attempts >= WORKER_MAX_RETRIES:
                _update_job_status(db, job, "failed", error=f"Max retries exceeded: {exc}")
                failed_count += 1
                _alert_on_failure(
                    alert.id,
                    f"Max retries ({WORKER_MAX_RETRIES}) exceeded: {exc}",
                    {"job_id": job.id, "kind": job.kind, "attempts": job.attempts, "error_type": "delivery"}
                )
            else:
                # Exponential backoff with jitter
                delay = WORKER_RETRY_BASE_DELAY_SECONDS * (2 ** (job.attempts - 1))
                job.due_at = utc_now() + timedelta(seconds=delay)
                job.last_error = type(exc).__name__
                db.commit()
                logger.warning(
                    "notification_retry_scheduled",
                    extra={
                        "alert_id": alert.id,
                        "kind": job.kind,
                        "attempt": job.attempts,
                        "next_retry_seconds": delay
                    }
                )

        except OperationalError as exc:
            # Database connection issues - don't count as attempt, just rollback
            db.rollback()
            logger.exception(
                "notification_db_error",
                extra={"job_id": job.id, "error_type": "operational"}
            )
            # Re-queue the job for immediate retry
            job.due_at = utc_now()

        except SQLAlchemyError as exc:
            db.rollback()
            job.attempts += 1
            logger.exception(
                "notification_db_error",
                extra={"job_id": job.id, "attempt": job.attempts, "error_type": type(exc).__name__}
            )

        except Exception as exc:
            job.attempts += 1
            if job.attempts >= WORKER_MAX_RETRIES:
                _update_job_status(db, job, "failed", error=f"Unexpected error: {exc}")
                failed_count += 1
                _alert_on_failure(
                    alert.id,
                    f"Unexpected error after {WORKER_MAX_RETRIES} attempts: {exc}",
                    {"job_id": job.id, "kind": job.kind, "attempts": job.attempts, "error_type": "unexpected"}
                )
            else:
                delay = WORKER_RETRY_BASE_DELAY_SECONDS * (2 ** (job.attempts - 1))
                job.due_at = utc_now() + timedelta(seconds=delay)
                job.last_error = type(exc).__name__
                db.commit()
                logger.exception(
                    "notification_unexpected_error",
                    extra={
                        "alert_id": alert.id,
                        "kind": job.kind,
                        "attempt": job.attempts,
                        "next_retry_seconds": delay,
                        "error_type": type(exc).__name__
                    }
                )

    if failed_count > 0:
        logger.warning(
            "notification_batch_completed_with_failures",
            extra={"processed": processed_count, "failed": failed_count, "total": count}
        )
    elif processed_count > 0:
        logger.info(
            "notification_batch_completed",
            extra={"processed": processed_count, "total": count}
        )

    return count
