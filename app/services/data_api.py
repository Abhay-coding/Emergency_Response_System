"""Aurora Data API and DynamoDB idempotency primitives for the AWS demo.

These classes are deliberately independent of FastAPI and SQLAlchemy so they
can be tested locally with fakes and reused by the production-only routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class DataApiError(RuntimeError):
    """Raised when an Aurora Data API transaction cannot be completed."""


@dataclass(frozen=True)
class IdempotencyClaim:
    state: str
    alert_id: int | None = None


class DynamoIdempotencyLedger:
    """Small DynamoDB ledger that prevents concurrent duplicate submissions."""

    def __init__(self, table: Any, ttl_hours: int = 24) -> None:
        self._table = table
        self._ttl_hours = ttl_hours

    def claim(self, request_key: str, now: datetime | None = None) -> IdempotencyClaim:
        now = now or datetime.now(timezone.utc)
        expires_at = int((now + timedelta(hours=self._ttl_hours)).timestamp())
        try:
            self._table.put_item(
                Item={
                    "request_key": request_key,
                    "state": "in_progress",
                    "expires_at": expires_at,
                },
                ConditionExpression="attribute_not_exists(request_key)",
            )
            return IdempotencyClaim("claimed")
        except Exception as exc:
            item = self._table.get_item(Key={"request_key": request_key}).get("Item")
            if not item:
                raise DataApiError("Unable to claim idempotency key") from exc
            if item.get("state") == "completed" and item.get("alert_id") is not None:
                return IdempotencyClaim("completed", int(item["alert_id"]))
            return IdempotencyClaim("in_progress")

    def complete(self, request_key: str, alert_id: int) -> None:
        self._table.update_item(
            Key={"request_key": request_key},
            UpdateExpression="SET #state = :completed, alert_id = :alert_id",
            ConditionExpression="#state = :in_progress",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":completed": "completed",
                ":in_progress": "in_progress",
                ":alert_id": alert_id,
            },
        )


class AuroraAlertRepository:
    """Writes the minimum emergency alert and audit event atomically."""

    def __init__(self, client: Any, resource_arn: str, secret_arn: str, database: str) -> None:
        self._client = client
        self._resource_arn = resource_arn
        self._secret_arn = secret_arn
        self._database = database

    def _call(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return getattr(self._client, operation)(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            database=self._database,
            **kwargs,
        )

    def create_alert(self, *, idempotency_key: str, source: str, reporter_id: int | None = None) -> int:
        transaction_id = self._call("begin_transaction")["transactionId"]
        try:
            fields = [
                {"name": "idempotency_key", "value": {"stringValue": idempotency_key}},
                {"name": "source", "value": {"stringValue": source}},
            ]
            reporter_value: dict[str, Any] = {"isNull": True} if reporter_id is None else {"longValue": reporter_id}
            fields.append({"name": "reporter_id", "value": reporter_value})
            inserted = self._call(
                "execute_statement",
                transactionId=transaction_id,
                sql=(
                    "INSERT INTO medical_alerts "
                    "(idempotency_key, source, reporter_id, status, verification, created_at, updated_at) "
                    "VALUES (:idempotency_key, :source, :reporter_id, 'new', 'unverified', NOW(), NOW()) "
                    "RETURNING id"
                ),
                parameters=fields,
            )
            try:
                alert_id = int(inserted["records"][0][0]["longValue"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise DataApiError("Aurora did not return an alert ID") from exc
            self._call(
                "execute_statement",
                transactionId=transaction_id,
                sql="INSERT INTO alert_events (alert_id, action, created_at) VALUES (:alert_id, 'created', NOW())",
                parameters=[{"name": "alert_id", "value": {"longValue": alert_id}}],
            )
            self._call("commit_transaction", transactionId=transaction_id)
            return alert_id
        except Exception as exc:
            try:
                self._call("rollback_transaction", transactionId=transaction_id)
            except Exception:
                pass
            if isinstance(exc, DataApiError):
                raise
            raise DataApiError("Unable to create medical alert") from exc


class AuroraUserRepository:
    """Minimal Data API read model for the demo authentication routes."""

    def __init__(self, client: Any, resource_arn: str, secret_arn: str, database: str) -> None:
        self._alerts = AuroraAlertRepository(client, resource_arn, secret_arn, database)

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        result = self._alerts._call(
            "execute_statement",
            sql=("SELECT id, name, email, password_hash, role, must_reset_password "
                 "FROM users WHERE email = :email LIMIT 1"),
            parameters=[{"name": "email", "value": {"stringValue": email.lower()}}],
        )
        records = result.get("records", [])
        if not records:
            return None
        values = records[0]
        return {
            "id": int(values[0]["longValue"]), "name": values[1]["stringValue"],
            "email": values[2]["stringValue"], "password_hash": values[3]["stringValue"],
            "role": values[4]["stringValue"],
            "must_reset_password": values[5].get("booleanValue", False),
        }
