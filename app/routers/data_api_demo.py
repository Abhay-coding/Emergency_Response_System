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
    try:
        user=repo.find_user(int(decode_access_token(authorization.removeprefix("Bearer "))["sub"]))
        if not user: raise ValueError("User no longer exists")
        return user
    except Exception as exc: raise HTTPException(401, "Please sign in again") from exc

class AlertIn(BaseModel): source: str = Field(default="self", max_length=20)
class ActionIn(BaseModel): version: int = Field(ge=1); note: str | None = Field(default=None, max_length=1000)
class AssignIn(ActionIn): staff_id: int; method: str = Field(default="notification", pattern="^(call|notification)$")
class VerificationIn(ActionIn): verification: str = Field(pattern="^(in_progress|confirmed_need|suspected_false)$")
class RegisterIn(BaseModel): name: str = Field(min_length=2, max_length=100); email: str = Field(min_length=5, max_length=255); password: str = Field(min_length=8, max_length=128)
class DetailsIn(BaseModel): place_name: str | None = Field(default=None, max_length=100); location_text: str | None = Field(default=None, max_length=200); callback_phone: str | None = Field(default=None, max_length=30); details: str | None = Field(default=None, max_length=1000); latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False); longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False); accuracy_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
class ContactIn(BaseModel): name: str = Field(min_length=2, max_length=100); kind: str = Field(pattern="^(department|caretaker|warden|medical|backup)$"); phone: str | None = Field(default=None, max_length=30); shift: str = Field(default="all", pattern="^(all|day|night)$")
class ContactUpdateIn(BaseModel): name: str | None = Field(default=None, min_length=2, max_length=100); kind: str | None = Field(default=None, pattern="^(department|caretaker|warden|medical|backup)$"); phone: str | None = Field(default=None, max_length=30); shift: str | None = Field(default=None, pattern="^(all|day|night)$"); active: bool | None = None; outcome: str | None = Field(default=None, pattern="^(accepted|no_answer|unavailable)$"); delay_seconds: int | None = Field(default=None, ge=0, le=300)
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
def public_config(repo: DataAPIRepository = Depends(get_repo)):
    return {"campus_emergency_phone": None, "prototype": True, "demo_mode": bool(getattr(repo, "isolated_demo_mode", False))}

@router.post("/medical-alerts", status_code=201)
def create_alert(data: AlertIn, key: str = Header(..., alias="Idempotency-Key"), user=Depends(current_user), repo: DataAPIRepository = Depends(get_repo), claims: DynamoLedger = Depends(ledger)):
    try: key = str(UUID(key))
    except ValueError: raise HTTPException(422, "Idempotency-Key must be a UUID")
    claim = claims.claim(key)
    guest_token = hmac_new((settings.guest_token_secret or settings.jwt_secret).encode(), key.encode(), "sha256").hexdigest()
    if claim["state"] == "completed":
        existing=repo.alert(claim["alert_id"])
        if not existing: raise HTTPException(410, "This demo alert was cleared. Start a new request.")
        return {"id":claim["alert_id"],"status":existing["status"],"identity_verified":existing.get("identity_verified",False),"guest_token":guest_token}
    if claim["state"] != "claimed" and not getattr(repo,"supports_idempotent_create",False): raise HTTPException(409, "Request is already being processed", headers={"Retry-After":"2"})
    try:
        alert_id = repo.create_alert(idempotency_key=key, source=data.source, guest_token_hash=sha256(guest_token.encode()).hexdigest(), reporter_id=user["id"] if user else None)
        claims.complete(key, alert_id)
        existing=repo.alert(alert_id)
        return {"id":alert_id,"status":existing.get("status","new") if existing else "new","identity_verified":existing.get("identity_verified",bool(user)) if existing else bool(user),"guest_token":guest_token}
    except Exception as exc: raise HTTPException(503, "Unable to record medical alert") from exc

@router.get("/medical-alerts/admin/queue")
def queue(_: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    return [{k:v for k,v in alert.items() if k not in {"guest_token_hash","idempotency_key","pk","sk"}} for alert in repo.queue()]

@router.get("/medical-alerts/{alert_id}/public")
def public_status(alert_id:int, token:str=Header(..., alias="X-Alert-Token"), repo:DataAPIRepository=Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert: raise HTTPException(404,"Demo alert no longer exists")
    if alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403,"Alert access denied")
    result={key:alert.get(key) for key in ("id","status","verification","place_id","location_text","callback_phone","details","latitude","longitude","accuracy_m","location_captured_at","created_at","updated_at","version")}
    result["demo_team"]=alert.get("contact_name") if alert.get("status") in {"staff_alerted","medical_dispatched","en_route","arrived","resolved"} and alert.get("contact_outcome")=="accepted" else None
    public_events={"created":"new","claimed":"acknowledged","demo_medical_dispatched":"medical","demo_en_route":"en-route","demo_arrived":"arrived","demo_resolved":"resolved","resolved":"resolved"}
    history=[]
    for event in repo.events(alert_id):
        stage=public_events.get(event.get("action"))
        if event.get("action")=="demo_contact_result" and "— accepted." in (event.get("note") or ""): stage="staff"
        if stage: history.append({"stage":stage,"created_at":event.get("created_at")})
    result["history"]=history
    return result

@router.patch("/medical-alerts/{alert_id}/location")
def update_details(alert_id: int, data: DetailsIn, token: str = Header(..., alias="X-Alert-Token"), repo: DataAPIRepository = Depends(get_repo)):
    alert = repo.alert(alert_id)
    if not alert or alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403, "Alert access denied")
    values=data.model_dump(exclude_none=True)
    if ("latitude" in values) != ("longitude" in values): raise HTTPException(422,"Latitude and longitude must be supplied together")
    if "place_name" in values:
        place=repo.place_by_name(values.pop("place_name"))
        if not place: raise HTTPException(422, "Choose a campus place from the list")
        values["place_id"]=place["id"]
    if not values: raise HTTPException(422, "Add at least one detail")
    updated=repo.update_alert_details(alert_id, **values)
    if not updated: raise HTTPException(404,"Alert not found")
    return {k:v for k,v in updated.items() if k not in {"guest_token_hash","idempotency_key","pk","sk"}}

@router.post("/medical-alerts/{alert_id}/escalate")
def escalate(alert_id: int, token: str = Header(..., alias="X-Alert-Token"), repo: DataAPIRepository = Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert: raise HTTPException(404, "Demo alert no longer exists")
    if alert.get("guest_token_hash") != sha256(token.encode()).hexdigest(): raise HTTPException(403, "Alert access denied")
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

def require_open_alert(repo, alert_id: int):
    alert=repo.alert(alert_id)
    if not alert: raise HTTPException(404,"Alert not found")
    if alert.get("status") in {"resolved","closed_false_report"}: raise HTTPException(409,"This alert is closed")
    return alert

@router.post("/demo/reset")
def reset_demo(_: dict = Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    if not hasattr(repo, "reset_demo_alerts"): raise HTTPException(503, "Demo reset is unavailable")
    return {"deleted_items":repo.reset_demo_alerts(), "message":"Demo alerts and their activity were cleared; contacts and other records were retained."}

@router.post("/medical-alerts/{alert_id}/claim")
def claim(alert_id:int, data:ActionIn, user=Depends(admin), repo:DataAPIRepository=Depends(get_repo)):
    current=require_open_alert(repo,alert_id)
    if current.get("status") not in {"new","acknowledged","checking"}: raise HTTPException(409,"This alert has already progressed beyond review")
    if current.get("claimed_by") and current["claimed_by"] != user["id"]: raise HTTPException(409,"This alert is already claimed by another admin")
    result=repo.conditional_action(alert_id,data.version,user["id"],status="acknowledged",action="claimed",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/verify")
def verify(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    require_open_alert(repo,alert_id)
    if not data.note or len(data.note.strip()) < 2: raise HTTPException(422,"Enter verification notes")
    result=repo.conditional_action(alert_id,data.version,user["id"],verification="confirmed_need",action="need_confirmed",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/verification")
def update_verification(alert_id:int,data:VerificationIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    require_open_alert(repo,alert_id)
    if not data.note or len(data.note.strip()) < 2: raise HTTPException(422,"Enter verification notes")
    result=repo.conditional_action(alert_id,data.version,user["id"],verification=data.verification,action="verification_"+data.verification,note=data.note.strip())
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/contact")
def contact(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    current=require_open_alert(repo,alert_id)
    if current.get("status") not in {"new","acknowledged","checking"}: raise HTTPException(409,"This alert has already progressed beyond review")
    if not data.note or len(data.note.strip()) < 2: raise HTTPException(422,"Enter contact notes")
    result=repo.conditional_action(alert_id,data.version,user["id"],status="checking",action="contact_attempt",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/staff")
def assign(alert_id:int,data:AssignIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    current=require_open_alert(repo,alert_id)
    if current.get("status") in {"contact_pending","medical_dispatched","en_route","arrived"}: raise HTTPException(409,"Contact cannot be changed at this stage")
    if not any(c["id"] == data.staff_id and c.get("active") for c in repo.contacts()): raise HTTPException(422,"Choose an available demo contact")
    result=repo.assign_staff(alert_id,data.version,user["id"],data.staff_id,data.method)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return {"alert":result,"notification":"demo_notification_recorded"}

@router.post("/medical-alerts/{alert_id}/staff-acknowledged")
def staff_acknowledged(alert_id: int, data: ActionIn, user=Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    current=require_open_alert(repo,alert_id)
    if current.get("status") not in {"staff_alerted","medical_dispatched","en_route","arrived"}: raise HTTPException(409,"No accepted demo contact is available")
    result=repo.conditional_action(alert_id,data.version,user["id"],action="staff_acknowledged",note=data.note or "Acknowledgement recorded by admin")
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/staff-findings")
def staff_findings(alert_id: int, data: ActionIn, user=Depends(admin), repo: DataAPIRepository = Depends(get_repo)):
    current=require_open_alert(repo,alert_id)
    if current.get("status") not in {"staff_alerted","medical_dispatched","en_route","arrived"}: raise HTTPException(409,"No accepted demo contact is available")
    if not data.note or len(data.note) < 2: raise HTTPException(422,"Enter staff findings")
    result=repo.conditional_action(alert_id,data.version,user["id"],action="staff_findings",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/dispatch-medical")
def dispatch(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert or alert.get("status") != "staff_alerted": raise HTTPException(409,"Simulate an accepted staff contact before dispatch")
    if not data.note or len(data.note.strip()) < 2: raise HTTPException(422,"Enter dispatch notes")
    result=repo.conditional_action(alert_id,data.version,user["id"],status="medical_dispatched",action="demo_medical_dispatched",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/demo-progress")
def demo_progress(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    alert=repo.alert(alert_id)
    if not alert: raise HTTPException(404,"Alert not found")
    transitions={"medical_dispatched":"en_route", "en_route":"arrived", "arrived":"resolved"}
    next_status=transitions.get(alert.get("status"))
    if not next_status: raise HTTPException(409,"No further demo progress is available")
    if next_status == "resolved" and (not data.note or len(data.note.strip()) < 2): raise HTTPException(422,"Enter resolution notes")
    result=repo.conditional_action(alert_id,data.version,user["id"],status=next_status,action=f"demo_{next_status}",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/resolve")
def resolve(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    require_open_alert(repo,alert_id)
    if not data.note or len(data.note.strip()) < 2: raise HTTPException(422,"Enter resolution notes")
    result=repo.conditional_action(alert_id,data.version,user["id"],status="resolved",action="resolved",note=data.note)
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result

@router.post("/medical-alerts/{alert_id}/close-false")
def reject(alert_id:int,data:ActionIn,user=Depends(admin),repo:DataAPIRepository=Depends(get_repo)):
    require_open_alert(repo,alert_id)
    if not data.note or len(data.note.strip()) < 10: raise HTTPException(422,"A clear rejection reason is required")
    result=repo.conditional_action(alert_id,data.version,user["id"],status="closed_false_report",verification="confirmed_false",action="closed_false_report",note=data.note.strip())
    if not result: raise HTTPException(409,"Alert changed; refresh and retry")
    return result
