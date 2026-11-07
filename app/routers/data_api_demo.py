"""Minimal Data API-backed routes for the deployed course demo."""
from uuid import UUID
from hashlib import sha256
from hmac import new as hmac_new

from fastapi import APIRouter, Depends, Form, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.security import create_access_token, decode_access_token, verify_password
from app.data_api_repository import DataAPIRepository, DynamoLedger, get_repo
from app.core.config import settings

router = APIRouter(tags=["Data API demo"])

def ledger() -> DynamoLedger:
    import os
    table = os.getenv("IDEMPOTENCY_TABLE")
    if not table: raise HTTPException(503, "Idempotency service is not configured")
    return DynamoLedger(table)

def admin(authorization: str = Header(...), repo: DataAPIRepository = Depends(get_repo)):
    try: user = repo.find_user(int(decode_access_token(authorization.removeprefix("Bearer "))["sub"]))
    except Exception as exc: raise HTTPException(401, "Invalid credentials") from exc
    if not user or user["role"] != "admin": raise HTTPException(403, "Admin access required")
    return user

class AlertIn(BaseModel): source: str = Field(default="self", max_length=20)
class ActionIn(BaseModel): version: int = Field(ge=1); note: str | None = Field(default=None, max_length=1000)
class AssignIn(ActionIn): staff_id: int

@router.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), repo: DataAPIRepository = Depends(get_repo)):
    user = repo.find_user_by_email(username)
    if not user or not verify_password(password, user["password_hash"]): raise HTTPException(401, "Incorrect email or password")
    if user.get("must_reset_password"): raise HTTPException(401, "Password reset required")
    return {"access_token": create_access_token(str(user["id"])), "token_type":"bearer"}

@router.get("/auth/me")
def me(user=Depends(admin)): return user

@router.get("/medical-alerts/places")
def places(repo: DataAPIRepository = Depends(get_repo)): return repo.places()

@router.get("/medical-alerts/config")
def public_config():
    return {"campus_emergency_phone": None, "prototype": True}

@router.post("/medical-alerts", status_code=201)
def create_alert(data: AlertIn, key: str = Header(..., alias="Idempotency-Key"), repo: DataAPIRepository = Depends(get_repo), claims: DynamoLedger = Depends(ledger)):
    try: key = str(UUID(key))
    except ValueError: raise HTTPException(422, "Idempotency-Key must be a UUID")
    claim = claims.claim(key)
    guest_token = hmac_new((settings.guest_token_secret or settings.jwt_secret).encode(), key.encode(), "sha256").hexdigest()
    if claim["state"] == "completed": return {"id":claim["alert_id"],"status":"new","identity_verified":False,"guest_token":guest_token}
    if claim["state"] != "claimed": raise HTTPException(409, "Request is already being processed", headers={"Retry-After":"2"})
    try:
        alert_id = repo.create_alert(idempotency_key=key, source=data.source, guest_token_hash=sha256(guest_token.encode()).hexdigest())
        claims.complete(key, alert_id)
        return {"id":alert_id,"status":"new","identity_verified":False,"guest_token":guest_token}
    except Exception as exc: raise HTTPException(503, "Unable to record medical alert") from exc

@router.get("/medical-alerts/admin/queue")
def queue(_: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)): return repo.queue()

@router.get("/medical-alerts/{alert_id}/public")
def public_status(alert_id:int, token:str=Header(..., alias="X-Alert-Token"), repo:DataAPIRepository=Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert or alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403,"Alert access denied")
    return {key:alert.get(key) for key in ("id","status","verification","place_id","location_text","created_at","version")}

@router.get("/medical-alerts/{alert_id}/events")
def events(alert_id:int, _:dict=Depends(admin), repo:DataAPIRepository=Depends(get_repo)):
    if not repo.alert(alert_id): raise HTTPException(404,"Alert not found")
    return repo.events(alert_id)

@router.get("/campus/contacts")
def contacts(_: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)): return repo.contacts()

@router.get("/campus/operations")
def operations(_: dict = Depends(admin)):
    return {"notification_mode":"simulation", "live_ready":False, "failed_jobs":0, "sqs_configured":False, "backup_configured":False, "campus_emergency_phone_configured":False}

@router.post("/medical-alerts/{alert_id}/claim")
def claim(alert_id:int, data:ActionIn, user=Depends(admin), repo:DataAPIRepository=Depends(get_repo)):
    result=repo.conditional_action(alert_id,data.version,user["id"],status="acknowledged",action="claimed",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/verify")
def verify(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    result=repo.conditional_action(alert_id,data.version,user["id"],verification="confirmed_need",action="need_confirmed",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/contact")
def contact(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    result=repo.conditional_action(alert_id,data.version,user["id"],status="checking",action="contact_attempt",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/staff")
def assign(alert_id:int,data:AssignIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    result=repo.assign_staff(alert_id,data.version,user["id"],data.staff_id)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return {"alert":result,"notification":"demo_notification_recorded"}

@router.post("/medical-alerts/{alert_id}/dispatch-medical")
def dispatch(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    result=repo.conditional_action(alert_id,data.version,user["id"],status="medical_dispatched",action="medical_dispatched",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/resolve")
def resolve(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    result=repo.conditional_action(alert_id,data.version,user["id"],status="resolved",action="resolved",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/close-false")
def reject(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    if not data.note or len(data.note) < 10: raise HTTPException(422,"A clear rejection reason is required")
    result=repo.conditional_action(alert_id,data.version,user["id"],status="closed_false_report",verification="confirmed_false",action="closed_false_report",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result
