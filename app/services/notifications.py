"""Durable outbound notification processing.

The database is the source of truth so an ECS worker can resume jobs after
restart. A message sent through SNS is marked sent only after SNS accepts it.
"""

import logging
import json
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MedicalAlert, NotificationJob, StaffContact, utc_now

logger = logging.getLogger(__name__)


def queue_job(job: NotificationJob) -> None:
    """Wake the cloud worker; the DB job remains authoritative if SQS is unavailable."""
    if not settings.aws_sqs_queue_url:
        return
    try:
        import boto3
        delay = max(0, min(900, int((job.due_at.replace(tzinfo=None) - utc_now().replace(tzinfo=None)).total_seconds())))
        boto3.client("sqs", region_name=settings.aws_region).send_message(
            QueueUrl=settings.aws_sqs_queue_url,
            MessageBody=json.dumps({"job_id": job.id}),
            DelaySeconds=delay,
        )
    except Exception:
        logger.exception("sqs_wakeup_failed", extra={"job_id": job.id})


def receive_wakeups() -> None:
    if not settings.aws_sqs_queue_url:
        return
    import boto3
    client = boto3.client("sqs", region_name=settings.aws_region)
    response = client.receive_message(QueueUrl=settings.aws_sqs_queue_url,
                                      MaxNumberOfMessages=10, WaitTimeSeconds=3)
    # A wakeup is only a hint. The DB poll below always checks due jobs.
    for message in response.get("Messages", []):
        client.delete_message(QueueUrl=settings.aws_sqs_queue_url,
                              ReceiptHandle=message["ReceiptHandle"])


def _phone_for_job(db: Session, job: NotificationJob) -> str:
    if job.kind == "backup_escalation":
        if not settings.backup_phone:
            raise ValueError("Backup phone is not configured")
        return settings.backup_phone
    contact = db.get(StaffContact, job.staff_id) if job.staff_id else None
    if not contact or not contact.phone:
        raise ValueError("Staff phone is not configured")
    return contact.phone


def _send(phone: str, alert_id: int, kind: str) -> None:
    if settings.notification_mode != "sns":
        raise ValueError("Outbound notification provider is not configured")
    import boto3
    client = boto3.client("sns", region_name=settings.aws_region)
    # Avoid medical details in SMS, logs, and AWS delivery records.
    client.publish(
        PhoneNumber=phone,
        Message=f"Campus medical assistance alert #{alert_id}. Open the staff portal or contact the campus admin now.",
        MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}},
    )


def process_due_jobs(db: Session, limit: int = 25) -> int:
    """Process due jobs. Multiple workers recheck state before sending.

    The row lock applies in PostgreSQL; SQLite local demos should run one worker.
    """
    now = utc_now()
    jobs = (db.query(NotificationJob)
            .filter(NotificationJob.status == "pending", NotificationJob.due_at <= now)
            .order_by(NotificationJob.due_at, NotificationJob.id)
            .with_for_update(skip_locked=True).limit(limit).all())
    count = 0
    for job in jobs:
        count += 1
        alert = db.get(MedicalAlert, job.alert_id)
        if not alert or alert.closed_at or (job.kind == "backup_escalation" and alert.acknowledged_at):
            job.status = "cancelled"
            db.commit()
            continue
        try:
            phone = _phone_for_job(db, job)
            if settings.notification_mode == "simulation":
                job.status = "simulated"
                logger.info("notification_simulated", extra={"alert_id": alert.id, "kind": job.kind})
            else:
                _send(phone, alert.id, job.kind)
                job.status = "sent"
                job.sent_at = utc_now()
            job.last_error = None
        except ValueError as exc:
            job.status = "failed"
            job.last_error = str(exc)
        except Exception as exc:
            job.attempts += 1
            job.last_error = type(exc).__name__
            if job.attempts >= 3:
                job.status = "failed"
            else:
                job.due_at = utc_now() + timedelta(seconds=30 * job.attempts)
            logger.exception("notification_delivery_failed", extra={"alert_id": job.alert_id, "kind": job.kind})
        db.commit()
    return count
