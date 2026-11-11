"""Pay-per-request DynamoDB store for the deployed course demo."""
from __future__ import annotations

import json
import os
import time
from threading import Lock
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.core.security import hash_password

PLACES = (("CSED Lab", "building"), ("Library", "building"), ("C Block", "building"), ("B Block", "building"), ("F Block", "building"), ("G Block", "building"), ("Main Gate", "gate"), ("A Hostel", "hostel"), ("O Hostel", "hostel"), ("B Hostel", "hostel"), ("C Hostel", "hostel"), ("D Hostel", "hostel"), ("G Girls Hostel", "hostel"), ("N Girls Hostel", "hostel"), ("Q Girls Hostel", "hostel"), ("PG1 Girls Hostel", "hostel"), ("PG2 Girls Hostel", "hostel"), ("Electrical Department", "department"), ("Computer Department", "department"), ("Electronics Department", "department"))
CONTACTS = (("Campus Medical Centre", "medical", "all"), ("Campus Ambulance Team", "medical", "all"), ("Hostel Warden", "warden", "all"), ("Campus Security", "department", "all"), ("Emergency Response Coordinator", "department", "all"), ("Backup Medical Staff", "backup", "all"))
_seed_lock = Lock()
_seeded_tables: set[tuple[str, str, str | None]] = set()


class DynamoDemoRepository:
    supports_idempotent_create = True
    isolated_demo_mode = True
    def __init__(self, table_name: str | None = None, table: Any | None = None) -> None:
        if table is not None:
            self.table = table
            self._seed()
            return
        self.table = boto3.resource("dynamodb").Table(table_name or os.environ["DEMO_DATA_TABLE"])
        seed_key=(self.table.meta.client.meta.endpoint_url,self.table.name,os.getenv("BOOTSTRAP_ADMIN_SECRET_ARN"))
        # Keep independent resource instances per request, but seed once per
        # process. A failed setup is not cached and is retried on the next call.
        with _seed_lock:
            if seed_key not in _seeded_tables:
                self._seed()
                _seeded_tables.add(seed_key)

    @staticmethod
    def _now() -> str: return datetime.now(timezone.utc).isoformat()
    @staticmethod
    def _pk(alert_id: int) -> str: return f"DEMO#ALERT#{alert_id}"

    def _seed(self) -> None:
        secret_arn = os.getenv("BOOTSTRAP_ADMIN_SECRET_ARN")
        if secret_arn:
            secret = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"])
            try:
                self.table.put_item(Item={"pk":"USER#1", "sk":"PROFILE", "id":1, "name":"Campus Admin", "email":secret["email"].lower(), "password_hash":hash_password(secret["password"]), "role":"admin", "must_reset_password":False}, ConditionExpression="attribute_not_exists(pk)")
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
        for i, (name, kind) in enumerate(PLACES, 1):
            try:
                self.table.put_item(Item={"pk":"PLACE", "sk":f"{i:03}", "id":i, "name":name, "kind":kind, "active":True}, ConditionExpression="attribute_not_exists(pk)")
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
        for i, (name, kind, shift) in enumerate(CONTACTS, 1):
            try:
                self.table.put_item(Item={"pk":"DEMO#CONTACT", "sk":f"{i:03}", "id":i, "name":name, "kind":kind, "shift":shift, "active":True, "phone":f"DEMO-{i:03}", "demo":True, "outcome":"accepted", "delay_seconds":0}, ConditionExpression="attribute_not_exists(pk)")
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise

    def _all(self, **kwargs: Any) -> list[dict]:
        result = self.table.scan(**kwargs); items = result.get("Items", [])
        while result.get("LastEvaluatedKey"):
            result = self.table.scan(ExclusiveStartKey=result["LastEvaluatedKey"], **kwargs); items += result.get("Items", [])
        return items

    def find_user_by_email(self, email: str):
        email=email.strip().lower()
        key=sha256(email.encode()).hexdigest()
        index=self.table.get_item(Key={"pk":f"USER_EMAIL#{key}","sk":"INDEX"},ConsistentRead=True).get("Item")
        if index: return self.find_user(int(index["user_id"]))
        # Existing users and bootstrap admins predate the unique-email index.
        return next((x for x in self._all(ConsistentRead=True) if x.get("email") == email and x.get("sk") == "PROFILE"), None)
    def find_user(self, user_id: int):
        return self.table.get_item(Key={"pk":f"USER#{user_id}","sk":"PROFILE"},ConsistentRead=True).get("Item")
    def places(self): return sorted((x for x in self._all() if x.get("pk")=="PLACE" and x.get("active")), key=lambda x:x["name"])
    def contacts(self): return sorted((x for x in self._all() if x.get("pk")=="DEMO#CONTACT"), key=lambda x:x["name"])
    def place_by_name(self, name: str):
        return next((place for place in self.places() if place["name"].lower() == name.lower()), None)
    def alert(self, alert_id: int):
        item=self.table.get_item(Key={"pk":self._pk(alert_id),"sk":"META"}, ConsistentRead=True).get("Item")
        if item and item.get("status")=="contact_pending" and item.get("contact_due",0)<=int(time.time()):
            outcome=item.get("contact_outcome","unavailable")
            request={"Key":{"pk":self._pk(alert_id),"sk":"META"}, "UpdateExpression":"SET #s = :s, version = version + :one, updated_at = :now", "ConditionExpression":"#s = :pending AND version = :version", "ExpressionAttributeNames":{"#s":"status"}, "ExpressionAttributeValues":{":s":"staff_alerted" if outcome=="accepted" else "checking", ":pending":"contact_pending", ":version":item["version"], ":one":1, ":now":self._now()}}
            self._update_with_event(alert_id,request,"demo_contact_result",note=f"DEMO: {item.get('contact_name','Demo contact')} ({item.get('contact_phone','DEMO')}) — {outcome.replace('_',' ')}. No call or message sent.")
            return self.table.get_item(Key={"pk":self._pk(alert_id),"sk":"META"}, ConsistentRead=True).get("Item")
        return item
    def events(self, alert_id: int):
        # Read the alert's own partition consistently so a freshly committed
        # status never appears without its corresponding timeline event.
        params={"KeyConditionExpression":Key("pk").eq(self._pk(alert_id)) & Key("sk").begins_with("EVENT#"),"ConsistentRead":True}
        items=[]
        while True:
            page=self.table.query(**params)
            items.extend(page.get("Items", []))
            if not page.get("LastEvaluatedKey"): return items
            params["ExclusiveStartKey"]=page["LastEvaluatedKey"]
    def queue(self):
        rows=sorted((x for x in self._all(ConsistentRead=True) if x.get("sk")=="META" and x.get("pk","").startswith("DEMO#ALERT#")), key=lambda x:x["created_at"], reverse=True)[:100]
        return [self.alert(row["id"]) or row for row in rows]

    def _next_id(self) -> int:
        return int(self.table.update_item(Key={"pk":"COUNTER","sk":"ALERT"}, UpdateExpression="ADD #n :one", ExpressionAttributeNames={"#n":"next"}, ExpressionAttributeValues={":one":1}, ReturnValues="UPDATED_NEW")["Attributes"]["next"])
    def _event(self, alert_id:int, action:str, actor_id:int|None=None, note:str|None=None) -> None:
        self.table.put_item(Item={"pk":self._pk(alert_id),"sk":f"EVENT#{time.time_ns()}","action":action,"actor_id":actor_id,"note":note,"created_at":self._now()})
    def _update_with_event(self, alert_id:int, request:dict, action:str, actor_id:int|None=None, note:str|None=None) -> bool:
        request={"TableName":self.table.name, **request}
        event={"pk":self._pk(alert_id),"sk":f"EVENT#{time.time_ns()}","action":action,"actor_id":actor_id,"note":note,"created_at":request["ExpressionAttributeValues"][":now"]}
        try:
            self.table.meta.client.transact_write_items(TransactItems=[
                {"Update":request},
                {"Put":{"TableName":self.table.name,"Item":event,"ConditionExpression":"attribute_not_exists(pk)"}},
            ])
        except ClientError as exc:
            reasons=exc.response.get("CancellationReasons", [])
            if exc.response["Error"]["Code"] == "TransactionCanceledException" and reasons and reasons[0].get("Code") == "ConditionalCheckFailed": return False
            raise
        return True
    def create_alert(self, *, idempotency_key:str, source:str, guest_token_hash:str, reporter_id: int | None = None) -> int:
        # The request key determines a JavaScript-safe ID; the conditional put
        # makes a retry safe even if the separate ledger completion failed.
        alert_id=int(sha256(idempotency_key.encode()).hexdigest()[:12],16); now=self._now()
        item={"pk":self._pk(alert_id),"sk":"META","id":alert_id,"source":source,"reporter_id":reporter_id,"identity_verified":bool(reporter_id),"guest_token_hash":guest_token_hash,"status":"new","verification":"unverified","version":1,"created_at":now,"updated_at":now,"idempotency_key":idempotency_key,"demo":True}
        try:
            self.table.put_item(Item=item,ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
            existing=self.table.get_item(Key={"pk":self._pk(alert_id),"sk":"META"},ConsistentRead=True).get("Item")
            if not existing or existing.get("idempotency_key") != idempotency_key: raise RuntimeError("Demo alert ID collision")
            item=existing
        try:
            self.table.put_item(Item={"pk":self._pk(alert_id),"sk":"EVENT#00000000000000000000","action":"created","actor_id":item.get("reporter_id"),"note":None,"created_at":item["created_at"]},ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
        return alert_id

    def register_student(self, name: str, email: str, password: str) -> dict | None:
        email=email.strip().lower()
        if self.find_user_by_email(email): return None
        user_id = int(self.table.update_item(Key={"pk":"COUNTER","sk":"USER"}, UpdateExpression="ADD #n :one", ExpressionAttributeNames={"#n":"next"}, ExpressionAttributeValues={":one":1}, ReturnValues="UPDATED_NEW")["Attributes"]["next"]) + 100
        user = {"pk":f"USER#{user_id}","sk":"PROFILE","id":user_id,"name":name,"email":email.lower(),"password_hash":hash_password(password),"role":"reporter","must_reset_password":False,"created_at":self._now()}
        index={"pk":f"USER_EMAIL#{sha256(email.encode()).hexdigest()}","sk":"INDEX","user_id":user_id}
        for attempt in range(3):
            try:
                self.table.meta.client.transact_write_items(TransactItems=[
                    {"Put":{"TableName":self.table.name,"Item":index,"ConditionExpression":"attribute_not_exists(pk)"}},
                    {"Put":{"TableName":self.table.name,"Item":user,"ConditionExpression":"attribute_not_exists(pk)"}},
                ])
                break
            except ClientError as exc:
                reasons=exc.response.get("CancellationReasons", [])
                if exc.response["Error"]["Code"] != "TransactionCanceledException" or not reasons: raise
                if reasons[0].get("Code") == "ConditionalCheckFailed": return None
                if any(reason.get("Code") == "TransactionConflict" for reason in reasons) and attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
        return user

    def update_alert_details(self, alert_id: int, **details: Any):
        alert = self.alert(alert_id)
        if not alert: return None
        if details.get("latitude") is not None and details.get("longitude") is not None:
            details["location_captured_at"]=self._now()
        values={":now":self._now(),":one":1}; sets=["updated_at = :now", "version = version + :one"]
        allowed={"place_id","location_text","callback_phone","details","latitude","longitude","accuracy_m","location_captured_at"}
        for field, value in details.items():
            if field in allowed and value is not None:
                token=f":{field}"; sets.append(f"{field} = {token}"); values[token]=Decimal(str(value)) if isinstance(value, float) else value
        self.table.update_item(Key={"pk":self._pk(alert_id),"sk":"META"},UpdateExpression="SET "+", ".join(sets),ConditionExpression="attribute_exists(pk)",ExpressionAttributeValues=values)
        self._event(alert_id,"details_updated")
        return self.alert(alert_id)

    def escalate_alert(self, alert_id: int):
        alert=self.alert(alert_id)
        if not alert: return None
        self._event(alert_id, "student_escalated", note="Student requested urgent follow-up")
        return alert

    def create_contact(self, name: str, kind: str, phone: str | None, shift: str) -> dict:
        contact_id=int(self.table.update_item(Key={"pk":"COUNTER","sk":"CONTACT"},UpdateExpression="ADD #n :one",ExpressionAttributeNames={"#n":"next"},ExpressionAttributeValues={":one":1},ReturnValues="UPDATED_NEW")["Attributes"]["next"]) + 100
        contact={"pk":"DEMO#CONTACT","sk":f"{contact_id:03}","id":contact_id,"name":name,"kind":kind,"phone":f"DEMO-{contact_id:03}","shift":shift,"active":True,"demo":True,"created_at":self._now()}
        self.table.put_item(Item=contact); return contact

    def update_contact(self, contact_id: int, **changes: Any):
        contact=next((x for x in self.contacts() if x["id"] == contact_id),None)
        if not contact: return None
        values={}; sets=[]; names={}
        for field in ("shift","active","name","kind","outcome","delay_seconds"):
            if field in changes:
                token=f":{field}"; alias=f"#{field}"; values[token]=changes[field]; names[alias]=field; sets.append(f"{alias} = {token}")
        if not sets: return contact
        self.table.update_item(Key={"pk":"DEMO#CONTACT","sk":contact["sk"]},UpdateExpression="SET "+", ".join(sets),ExpressionAttributeNames=names,ExpressionAttributeValues=values,ConditionExpression="attribute_exists(pk)")
        return next(x for x in self.contacts() if x["id"] == contact_id)

    def save_coverage(self, place_id: int, staff_id: int, rank: int) -> dict | None:
        if not next((x for x in self.places() if x["id"] == place_id), None): return None
        contact=next((x for x in self.contacts() if x["id"] == staff_id),None)
        if not contact: return None
        item={"pk":f"DEMO#COVERAGE#{place_id}","sk":f"{rank:03}#{staff_id}","place_id":place_id,"staff_id":staff_id,"rank":rank,"created_at":self._now()}
        self.table.put_item(Item=item); return item

    def coverage(self, place_id: int) -> list[dict]:
        contacts={x["id"]:x for x in self.contacts()}
        rows=sorted((x for x in self._all() if x.get("pk") == f"DEMO#COVERAGE#{place_id}"), key=lambda x:x["rank"])
        return [{**contacts[row["staff_id"]],"rank":row["rank"]} for row in rows if row["staff_id"] in contacts]

    def record_staff_response(self, alert_id: int, actor_id: int, kind: str, note: str):
        if not self.alert(alert_id): return None
        self._event(alert_id, kind, actor_id, note)
        return self.alert(alert_id)
    def conditional_action(self, alert_id:int, version:int, actor_id:int, *, status=None, verification=None, action:str, note=None):
        values={":old":version,":one":1,":now":self._now()}; sets=["version = version + :one","updated_at = :now"]
        names = None
        if status is not None:
            sets += ["#status = :status"]
            values[":status"]=status
            names = {"#status":"status"}
        if verification is not None: sets += ["verification = :verification"]; values[":verification"]=verification
        if action == "claimed": sets.append("claimed_by = :actor"); values[":actor"]=actor_id
        request = {"Key":{"pk":self._pk(alert_id),"sk":"META"}, "UpdateExpression":"SET "+", ".join(sets), "ConditionExpression":"version = :old", "ExpressionAttributeValues":values}
        if names:
            request["ExpressionAttributeNames"] = names
        if not self._update_with_event(alert_id,request,action,actor_id,note): return None
        return self.alert(alert_id)
    def assign_staff(self, alert_id:int, version:int, actor_id:int, staff_id:int, method:str="notification"):
        contact=next((c for c in self.contacts() if c["id"]==staff_id and c.get("active")),None)
        if not contact: return None
        outcome=contact.get("outcome","accepted")
        request={"Key":{"pk":self._pk(alert_id),"sk":"META"},"UpdateExpression":"SET #s = :pending, version = version + :one, updated_at = :now, contact_due = :due, contact_outcome = :outcome, contact_name = :name, contact_phone = :phone, contact_id = :contact","ConditionExpression":"version = :old AND #s <> :pending","ExpressionAttributeNames":{"#s":"status"},"ExpressionAttributeValues":{":old":version,":one":1,":now":self._now(),":pending":"contact_pending",":due":int(time.time())+int(contact.get("delay_seconds",0)),":outcome":outcome,":name":contact["name"],":phone":contact["phone"],":contact":staff_id}}
        if not self._update_with_event(alert_id,request,"demo_contact_attempt",actor_id,f"DEMO: simulated {method} to {contact['name']} ({contact['phone']}); result pending. No call or message sent."): return None
        return self.alert(alert_id)

    def reset_demo_alerts(self) -> int:
        # Never delete records outside the dedicated demo-alert partition prefix.
        items=[item for item in self._all() if item.get("pk", "").startswith("DEMO#ALERT#")]
        for item in items:
            self.table.delete_item(Key={"pk":item["pk"],"sk":item["sk"]})
        return len(items)
