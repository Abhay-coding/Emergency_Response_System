"""Run as a separate ECS service: python -m app.worker."""

import logging
import time

from app.database import SessionLocal
from app.services.notifications import process_due_jobs, receive_wakeups


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            try:
                receive_wakeups()
            except Exception:
                logging.exception("sqs_receive_failed_using_db_poll")
            with SessionLocal() as db:
                processed = process_due_jobs(db)
            time.sleep(1 if processed else 5)
        except KeyboardInterrupt:
            return
        except Exception:
            logging.exception("medical_notification_worker_error")
            time.sleep(5)


if __name__ == "__main__":
    main()
