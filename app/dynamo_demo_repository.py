"""Pay-per-request DynamoDB store for the deployed course demo."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.security import hash_password

PLACES = (("CSED Lab", "building"), ("Library", "building"), ("C Block", "building"), ("B Block", "building"), ("F Block", "building"), ("G Block", "building"), ("Main Gate", "gate"), ("A Hostel", "hostel"), ("O Hostel", "hostel"), ("B Hostel", "hostel"), ("C Hostel", "hostel"), ("D Hostel", "hostel"), ("G Girls Hostel", "hostel"), ("N Girls Hostel", "hostel"), ("Q Girls Hostel", "hostel"), ("PG1 Girls Hostel", "hostel"), ("PG2 Girls Hostel", "hostel"), ("Electrical Department", "department"), ("Computer Department", "department"), ("Electronics Department", "department"))
CONTACTS = (("Campus Medical Team", "medical", "all"), ("Hostel Day Caretaker", "caretaker", "day"), ("Hostel Night Caretaker", "caretaker", "night"), ("Hostel Warden", "warden", "all"))


class DynamoDemoRepository:
    def __init__(self, table_name: str | None = None, table: Any | None = None) -> None:
        self.table = table or boto3.resource("dynamodb").Table(table_name or os.environ["DEMO_DATA_TABLE"])
        self._seed()

    @staticmethod
    def _now() -> str: return datetime.now(timezone.utc).isoformat()
    @staticmethod
    def _pk(alert_id: int) -> str: return f"ALERT#{alert_id}"

    def _seed(self) -> None:
        secret_arn = os.getenv("BOOTSTRAP_ADMIN_SECRET_ARN")
        if not secret_arn: return
        secret = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"])
        try:
            self.table.put_item(Item={"pk":"USER#1", "sk":"PROFILE", "id":1, "name":"Campus Admin", "email":secret["email"].lower(), "password_hash":hash_password(secret["password"]), "role":"admin", "must_reset_password":False}, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
        for i, (name, kind) in enumerate(PLACES, 1):
            self.table.put_item(Item={"pk":"PLACE", "sk":f"{i:03}", "id":i, "name":name, "kind":kind, "active":True})
        for i, (name, kind, shift) in enumerate(CONTACTS, 1):
            self.table.put_item(Item={"pk":"CONTACT", "sk":f"{i:03}", "id":i, "name":name, "kind":kind, "shift":shift, "active":True})

    def _all(self, **kwargs: Any) -> list[dict]:
        result = self.table.scan(**kwargs); items = result.get("Items", [])
        while result.get("LastEvaluatedKey"):
            result = self.table.scan(ExclusiveStartKey=result["LastEvaluatedKey"], **kwargs); items += result.get("Items", [])
        return items

    def find_user_by_email(self, email: str):
        return next((x for x in self._all() if x.get("email") == email.lower()), None)
    def find_user(self, user_id: int):
        return self.table.get_item(Key={"pk":f"USER#{user_id}","sk":"PROFILE"}).get("Item")
    def places(self): return sorted((x for x in self._all() if x.get("pk")=="PLACE" and x.get("active")), key=lambda x:x["name"])
    def contacts(self): return sorted((x for x in self._all() if x.get("pk")=="CONTACT"), key=lambda x:x["name"])
    def alert(self, alert_id: int): return self.table.get_item(Key={"pk":self._pk(alert_id),"sk":"META"}).get("Item")
    def events(self, alert_id: int): return sorted((x for x in self._all() if x.get("pk")==self._pk(alert_id) and x.get("sk","").startswith("EVENT#")), key=lambda x:x["sk"])
    def queue(self): return sorted((x for x in self._all() if x.get("sk")=="META" and x.get("pk","").startswith("ALERT#")), key=lambda x:x["created_at"], reverse=True)[:100]

    def _next_id(self) -> int:
        return int(self.table.update_item(Key={"pk":"COUNTER","sk":"ALERT"}, UpdateExpression="ADD #n :one", ExpressionAttributeNames={"#n":"next"}, ExpressionAttributeValues={":one":1}, ReturnValues="UPDATED_NEW")["Attributes"]["next"])
    def _event(self, alert_id:int, action:str, actor_id:int|None=None, note:str|None=None) -> None:
        self.table.put_item(Item={"pk":self._pk(alert_id),"sk":f"EVENT#{time.time_ns()}","action":action,"actor_id":actor_id,"note":note,"created_at":self._now()})
    def create_alert(self, *, idempotency_key:str, source:str, guest_token_hash:str) -> int:
        alert_id=self._next_id(); now=self._now()
        self.table.put_item(Item={"pk":self._pk(alert_id),"sk":"META","id":alert_id,"source":source,"guest_token_hash":guest_token_hash,"status":"new","verification":"unverified","version":1,"created_at":now,"updated_at":now,"idempotency_key":idempotency_key})
        self._event(alert_id,"created"); return alert_id
    def conditional_action(self, alert_id:int, version:int, actor_id:int, *, status=None, verification=None, action:str, note=None):
        values={":old":version,":one":1,":now":self._now()}; sets=["version = version + :one","updated_at = :now"]
        if status is not None: sets += ["#status = :status"]; values[":status"]=status
        if verification is not None: sets += ["verification = :verification"]; values[":verification"]=verification
        try:
            self.table.update_item(Key={"pk":self._pk(alert_id),"sk":"META"},UpdateExpression="SET "+", ".join(sets),ConditionExpression="version = :old",ExpressionAttributeNames={"#status":"status"},ExpressionAttributeValues=values)
        except ClientError as exc:
            if exc.response["Error"]["Code"]=="ConditionalCheckFailedException": return None
            raise
        self._event(alert_id,action,actor_id,note); return self.alert(alert_id)
    def assign_staff(self, alert_id:int, version:int, actor_id:int, staff_id:int):
        result=self.conditional_action(alert_id,version,actor_id,status="staff_alerted",action="demo_notification_recorded",note="No external message was sent")
        if result: self.table.put_item(Item={"pk":self._pk(alert_id),"sk":f"ASSIGNMENT#{time.time_ns()}","staff_id":staff_id,"status":"simulated","created_at":self._now()})
        return result
