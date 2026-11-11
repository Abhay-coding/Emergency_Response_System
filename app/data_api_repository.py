"""Thin Aurora Data API repository used by the Lambda production path."""
import os
import time
from typing import Any

import boto3
from fastapi import HTTPException


class DataAPIRepository:
    def __init__(self, cluster_arn: str, secret_arn: str, database: str, client: Any | None = None):
        if not all((cluster_arn, secret_arn, database)):
            raise ValueError("Aurora Data API configuration is incomplete")
        self.client = client or boto3.client("rds-data")
        self.cluster_arn, self.secret_arn, self.database = cluster_arn, secret_arn, database

    def begin_transaction(self) -> str:
        return self.client.begin_transaction(resourceArn=self.cluster_arn, secretArn=self.secret_arn, database=self.database)["transactionId"]

    def execute(self, sql: str, params: list[dict], tx_id: str | None = None) -> dict:
        args = dict(resourceArn=self.cluster_arn, secretArn=self.secret_arn, database=self.database, sql=sql, parameters=params)
        if tx_id:
            args["transactionId"] = tx_id
        return self.client.execute_statement(**args)

    def commit(self, tx_id: str) -> None:
        self.client.commit_transaction(resourceArn=self.cluster_arn, secretArn=self.secret_arn, transactionId=tx_id)

    def rollback(self, tx_id: str) -> None:
        self.client.rollback_transaction(resourceArn=self.cluster_arn, secretArn=self.secret_arn, transactionId=tx_id)

    @staticmethod
    def _value(field: dict) -> Any:
        for key in ("stringValue", "longValue", "doubleValue", "booleanValue"):
            if key in field:
                return field[key]
        return None

    def query(self, sql: str, params: list[dict] | None = None) -> list[dict[str, Any]]:
        result = self.execute(sql, params or [])
        names = [column["name"] for column in result.get("columnMetadata", [])]
        return [dict(zip(names, (self._value(field) for field in row))) for row in result.get("records", [])]

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        rows = self.query(
            "SELECT id, name, email, password_hash, role, must_reset_password FROM users WHERE email = :email LIMIT 1",
            [{"name": "email", "value": {"stringValue": email.lower()}}],
        )
        return rows[0] if rows else None

    def find_user(self, user_id: int) -> dict[str, Any] | None:
        rows = self.query(
            "SELECT id, name, email, role FROM users WHERE id = :id LIMIT 1",
            [{"name": "id", "value": {"longValue": user_id}}],
        )
        return rows[0] if rows else None

    def places(self) -> list[dict[str, Any]]:
        return self.query("SELECT id, name, kind FROM campus_places WHERE active = true ORDER BY name")

    def contacts(self) -> list[dict[str, Any]]:
        return self.query("SELECT id, name, kind, phone, shift, active, user_id FROM staff_contacts ORDER BY name")

    def events(self, alert_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT action, note, actor_id, created_at FROM alert_events WHERE alert_id = :id ORDER BY id", [{"name":"id","value":{"longValue":alert_id}}])

    def alert(self, alert_id: int) -> dict[str, Any] | None:
        rows = self.query("SELECT id, source, status, verification, place_id, location_text, claimed_by, version, guest_token_hash, guest_token_expires_at, created_at FROM medical_alerts WHERE id = :id", [{"name":"id","value":{"longValue":alert_id}}])
        return rows[0] if rows else None

    def queue(self) -> list[dict[str, Any]]:
        return self.query("SELECT id, source, status, verification, place_id, location_text, claimed_by, version, created_at FROM medical_alerts ORDER BY created_at DESC LIMIT 100")

    def create_alert(self, *, idempotency_key: str, source: str, guest_token_hash: str) -> int:
        tx = self.begin_transaction()
        try:
            created = self.execute("INSERT INTO medical_alerts (idempotency_key, source, guest_token_hash, guest_token_expires_at, status, verification, version, created_at, updated_at) VALUES (:key, :source, :token, NOW() + INTERVAL '7 days', 'new', 'unverified', 1, NOW(), NOW()) RETURNING id", [{"name":"key","value":{"stringValue":idempotency_key}}, {"name":"source","value":{"stringValue":source}}, {"name":"token","value":{"stringValue":guest_token_hash}}], tx)
            alert_id = int(created["records"][0][0]["longValue"])
            self.execute("INSERT INTO alert_events (alert_id, action, created_at) VALUES (:id, 'created', NOW())", [{"name":"id","value":{"longValue":alert_id}}], tx)
            self.commit(tx)
            return alert_id
        except Exception:
            self.rollback(tx)
            raise

    def conditional_action(self, alert_id: int, version: int, actor_id: int, *, status: str | None = None, verification: str | None = None, action: str, note: str | None = None) -> dict[str, Any] | None:
        tx = self.begin_transaction()
        try:
            assignments = ["version = version + 1", "updated_at = NOW()"]
            params = [{"name":"id","value":{"longValue":alert_id}}, {"name":"version","value":{"longValue":version}}]
            if status is not None:
                assignments.append("status = :status"); params.append({"name":"status","value":{"stringValue":status}})
            if verification is not None:
                assignments.append("verification = :verification"); params.append({"name":"verification","value":{"stringValue":verification}})
            updated = self.execute(f"UPDATE medical_alerts SET {', '.join(assignments)} WHERE id = :id AND version = :version RETURNING id, status, verification, version", params, tx)
            if not updated.get("records"):
                self.rollback(tx); return None
            self.execute("INSERT INTO alert_events (alert_id, actor_id, action, note, created_at) VALUES (:alert_id, :actor_id, :action, :note, NOW())", [
                {"name":"alert_id","value":{"longValue":alert_id}}, {"name":"actor_id","value":{"longValue":actor_id}}, {"name":"action","value":{"stringValue":action}}, {"name":"note","value":{"isNull":note is None, **({"stringValue":note} if note else {})}},
            ], tx)
            self.commit(tx)
            return self.alert(alert_id)
        except Exception:
            self.rollback(tx); raise

    def assign_staff(self, alert_id: int, version: int, actor_id: int, staff_id: int, method: str = "notification") -> dict[str, Any] | None:
        tx = self.begin_transaction()
        try:
            updated = self.execute("UPDATE medical_alerts SET status = 'staff_alerted', version = version + 1, updated_at = NOW() WHERE id = :id AND version = :version RETURNING id", [{"name":"id","value":{"longValue":alert_id}},{"name":"version","value":{"longValue":version}}], tx)
            if not updated.get("records"):
                self.rollback(tx); return None
            self.execute("INSERT INTO alert_assignments (alert_id, staff_id, status, created_at) VALUES (:alert_id, :staff_id, 'simulated', NOW())", [{"name":"alert_id","value":{"longValue":alert_id}},{"name":"staff_id","value":{"longValue":staff_id}}], tx)
            self.execute("INSERT INTO alert_events (alert_id, actor_id, action, note, created_at) VALUES (:alert_id, :actor_id, 'demo_notification_recorded', 'No external message was sent', NOW())", [{"name":"alert_id","value":{"longValue":alert_id}},{"name":"actor_id","value":{"longValue":actor_id}}], tx)
            self.commit(tx)
            return self.alert(alert_id)
        except Exception:
            self.rollback(tx); raise


class DynamoLedger:
    """DynamoDB claim/complete adapter for one-tap alert idempotency."""
    def __init__(self, table_name: str, client: Any | None = None) -> None:
        self.table_name = table_name
        self.client = client or boto3.client("dynamodb")

    def claim(self, key: str) -> dict[str, Any]:
        now = int(time.time())
        try:
            self.client.put_item(TableName=self.table_name, Item={"request_key":{"S":key},"state":{"S":"in_progress"},"expires_at":{"N":str(now + 86400)}}, ConditionExpression="attribute_not_exists(request_key)")
            return {"state":"claimed"}
        except self.client.exceptions.ConditionalCheckFailedException:
            item = self.client.get_item(TableName=self.table_name, Key={"request_key":{"S":key}}).get("Item", {})
            if item.get("state", {}).get("S") == "completed":
                return {"state":"completed", "alert_id":int(item["alert_id"]["N"])}
            return {"state":"in_progress"}

    def complete(self, key: str, alert_id: int) -> None:
        self.client.update_item(TableName=self.table_name, Key={"request_key":{"S":key}}, UpdateExpression="SET #s = :s, alert_id = :id", ExpressionAttributeNames={"#s":"state"}, ExpressionAttributeValues={":s":{"S":"completed"},":id":{"N":str(alert_id)}})


def get_repo() -> DataAPIRepository:
    if os.getenv("DYNAMO_DEMO_ENABLED", "").lower() == "true":
        from app.dynamo_demo_repository import DynamoDemoRepository
        return DynamoDemoRepository()  # type: ignore[return-value]
    try:
        return DataAPIRepository(os.getenv("AURORA_CLUSTER_ARN", ""), os.getenv("AURORA_SECRET_ARN", ""), os.getenv("AURORA_DATABASE", ""))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Cloud database is not configured") from exc
