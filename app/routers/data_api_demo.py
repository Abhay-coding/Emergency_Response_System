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

def current_user(authorization: str | None = Header(default=None), repo: DataAPIRepository = Depends(get_repo)):
    if not authorization: return None
    try: return repo.find_user(int(decode_access_token(authorization.removeprefix("Bearer "))["sub"]))
    except Exception as exc: raise HTTPException(401, "Please sign in again") from exc

class AlertIn(BaseModel): source: str = Field(default="self", max_length=20)
class ActionIn(BaseModel): version: int = Field(ge=1); note: str | None = Field(default=None, max_length=1000)
class AssignIn(ActionIn): staff_id: int
class RegisterIn(BaseModel): name: str = Field(min_length=2, max_length=100); email: str = Field(min_length=5, max_length=255); password: str = Field(min_length=8, max_length=128)
class DetailsIn(BaseModel): place_name: str | None = Field(default=None, max_length=100); location_text: str | None = Field(default=None, max_length=200); callback_phone: str | None = Field(default=None, max_length=30); details: str | None = Field(default=None, max_length=1000); latitude: float | None = None; longitude: float | None = None; accuracy_m: float | None = None
class ContactIn(BaseModel): name: str = Field(min_length=2, max_length=100); kind: str = Field(pattern="^(department|caretaker|warden|medical|backup)$"); phone: str | None = Field(default=None, max_length=30); shift: str = Field(default="all", pattern="^(all|day|night)$")
class ContactUpdateIn(BaseModel): name: str | None = Field(default=None, min_length=2, max_length=100); kind: str | None = Field(default=None, pattern="^(department|caretaker|warden|medical|backup)$"); phone: str | None = Field(default=None, max_length=30); shift: str | None = Field(default=None, pattern="^(all|day|night)$"); active: bool | None = None
class CoverageIn(BaseModel): place_id: int = Field(gt=0); staff_id: int = Field(gt=0); rank: int = Field(ge=1, le=100)

@router.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), repo: DataAPIRepository = Depends(get_repo)):
    user = repo.find_user_by_email(username)
    if not user or not verify_password(password, user["password_hash"]): raise HTTPException(401, "Incorrect email or password")
    if user.get("must_reset_password"): raise HTTPException(401, "Password reset required")
    return {"access_token": create_access_token(str(user["id"])), "token_type":"bearer"}

@router.post("/auth/register", status_code=201)
def register(data: RegisterIn, repo: DataAPIRepository = Depends(get_repo)):
    user = repo.register_student(data.name.strip(), data.email.strip().lower(), data.password)
    if not user: raise HTTPException(409, "An account already exists for that email")
    return {"id":user["id"],"name":user["name"],"email":user["email"],"role":user["role"]}

@router.get("/auth/me")
def me(user=Depends(current_user)):
    if not user: raise HTTPException(401, "Please sign in")
    return {key:value for key,value in user.items() if key not in {"password_hash","pk","sk"}}

@router.get("/medical-alerts/places")
def places(repo: DataAPIRepository = Depends(get_repo)): return repo.places()

@router.get("/medical-alerts/config")
def public_config():
    return {"campus_emergency_phone": None, "prototype": True}

@router.post("/medical-alerts", status_code=201)
def create_alert(data: AlertIn, key: str = Header(..., alias="Idempotency-Key"), user=Depends(current_user), repo: DataAPIRepository = Depends(get_repo), claims: DynamoLedger = Depends(ledger)):
    try: key = str(UUID(key))
    except ValueError: raise HTTPException(422, "Idempotency-Key must be a UUID")
    claim = claims.claim(key)
    guest_token = hmac_new((settings.guest_token_secret or settings.jwt_secret).encode(), key.encode(), "sha256").hexdigest()
    if claim["state"] == "completed": return {"id":claim["alert_id"],"status":"new","identity_verified":False,"guest_token":guest_token}
    if claim["state"] != "claimed": raise HTTPException(409, "Request is already being processed", headers={"Retry-After":"2"})
    try:
        alert_id = repo.create_alert(idempotency_key=key, source=data.source, guest_token_hash=sha256(guest_token.encode()).hexdigest(), reporter_id=user["id"] if user else None)
        claims.complete(key, alert_id)
        return {"id":alert_id,"status":"new","identity_verified":bool(user),"guest_token":guest_token}
    except Exception as exc: raise HTTPException(503, "Unable to record medical alert") from exc

@router.get("/medical-alerts/admin/queue")
def queue(_: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)): return repo.queue()

@router.get("/medical-alerts/{alert_id}/public")
def public_status(alert_id:int, token:str=Header(..., alias="X-Alert-Token"), repo:DataAPIRepository=Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert or alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403,"Alert access denied")
    return {key:alert.get(key) for key in ("id","status","verification","place_id","location_text","callback_phone","details","latitude","longitude","accuracy_m","created_at","version")}

@router.patch("/medical-alerts/{alert_id}/location")
def update_details(alert_id: int, data: DetailsIn, token: str = Header(..., alias="X-Alert-Token"), repo: DataAPIRepository = Depends(get_repo)):
    alert = repo.alert(alert_id)
    if not alert or alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403, "Alert access denied")
    values=data.model_dump(exclude_none=True)
    if "place_name" in values:
        place=repo.place_by_name(values.pop("place_name"))
        if not place: raise HTTPException(422, "Choose a campus place from the list")
        values["place_id"]=place["id"]
    if not values: raise HTTPException(422, "Add at least one detail")
    return repo.update_alert_details(alert_id, **values)

@router.post("/medical-alerts/{alert_id}/escalate")
def escalate(alert_id: int, token: str = Header(..., alias="X-Alert-Token"), repo: DataAPIRepository = Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert or alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403, "Alert access denied")
    return repo.escalate_alert(alert_id)

@router.get("/medical-alerts/{alert_id}/events")
def events(alert_id:int, _:dict=Depends(admin), repo:DataAPIRepository=Depends(get_repo)):
    if not repo.alert(alert_id): raise HTTPException(404,"Alert not found")
    return repo.events(alert_id)

@router.get("/campus/contacts")
def contacts(_: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)): return repo.contacts()

@router.post("/campus/contacts", status_code=201)
def create_contact(data: ContactIn, _: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    return repo.create_contact(data.name.strip(), data.kind, data.phone.strip() if data.phone else None, data.shift)

@router.patch("/campus/contacts/{contact_id}")
def update_contact(contact_id: int, data: ContactUpdateIn, _: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    result=repo.update_contact(contact_id, **data.model_dump(exclude_unset=True))
    if not result: raise HTTPException(404, "Contact not found")
    return result

@router.get("/campus/coverage/{place_id}")
def coverage(place_id: int, _: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)): return repo.coverage(place_id)

@router.post("/campus/coverage", status_code=201)
def save_coverage(data: CoverageIn, _: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    result=repo.save_coverage(data.place_id,data.staff_id,data.rank)
    if not result: raise HTTPException(422, "Choose an existing campus place and contact")
    return result

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

@router.post("/medical-alerts/{alert_id}/staff-acknowledged")
def staff_acknowledged(alert_id: int, data: ActionIn, user=Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    result=repo.record_staff_response(alert_id,user["id"],"staff_acknowledged",data.note or "Acknowledgement recorded by admin")
    if not result: raise HTTPException(404,"Alert not found")
    return result

@router.post("/medical-alerts/{alert_id}/staff-findings")
def staff_findings(alert_id: int, data: ActionIn, user=Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    if not data.note or len(data.note) < 2: raise HTTPException(422,"Enter staff findings")
    result=repo.record_staff_response(alert_id,user["id"],"staff_findings",data.note)
    if not result: raise HTTPException(404,"Alert not found")
    return result

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
