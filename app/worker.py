"""Run as a separate ECS service: python -m app.worker."""

import logging
import signal
import sys
import time
from threading import Event

from app.core.constants import (
    WORKER_POLL_INTERVAL_ACTIVE_SECONDS,
    WORKER_POLL_INTERVAL_IDLE_SECONDS,
    WORKER_SQS_WAIT_TIME_SECONDS,
    WORKER_SQS_MAX_MESSAGES,
)
from app.database import SessionLocal
from app.services.notifications import process_due_jobs, receive_wakeups

# Global shutdown event
shutdown_event = Event()

# Error tracking for exponential backoff
MAX_CONSECUTIVE_ERRORS = 10
BASE_ERROR_WAIT_SECONDS = 5
MAX_ERROR_WAIT_SECONDS = 300  # 5 minutes


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals gracefully"""
    logging.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger = logging.getLogger(__name__)
    logger.info("Medical notification worker started")

    consecutive_errors = 0

    while not shutdown_event.is_set():
        try:
            try:
                receive_wakeups()
            except Exception:
                logging.exception("sqs_receive_failed_using_db_poll")

            with SessionLocal() as db:
                processed = process_due_jobs(db)

            # Reset error counter on successful iteration
            if consecutive_errors > 0:
                logger.info(f"Worker recovered after {consecutive_errors} consecutive errors")
            consecutive_errors = 0

            # Use wait with timeout instead of sleep for responsive shutdown
            # Use constants for polling intervals
            poll_interval = (
                WORKER_POLL_INTERVAL_ACTIVE_SECONDS
                if processed
                else WORKER_POLL_INTERVAL_IDLE_SECONDS
            )
            shutdown_event.wait(timeout=poll_interval)
        except Exception:
            consecutive_errors += 1
            logging.exception("medical_notification_worker_error")

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.critical(f"Worker encountered {consecutive_errors} consecutive errors. Stopping worker.")
                break

            # Exponential backoff with cap
            error_wait = min(
                BASE_ERROR_WAIT_SECONDS * (2 ** (consecutive_errors - 1)),
                MAX_ERROR_WAIT_SECONDS
            )
            logger.warning(f"Worker error #{consecutive_errors}, waiting {error_wait}s before retry")
            shutdown_event.wait(timeout=error_wait)

    logger.info("Medical notification worker stopped gracefully")


if __name__ == "__main__":
    main()
