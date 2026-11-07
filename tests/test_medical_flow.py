import os
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "test-secret-for-medical-flow-long-enough")

from app.database import Base, get_db
from app.main import app
from app.models import MedicalAlert, Role, User, utc_now
from app.core.security import create_access_token, hash_password


def client_with_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with maker() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), maker


def add_user(maker, email, role):
    with maker() as db:
        user = User(name=email.split("@")[0], email=email,
                    password_hash=hash_password("Password1!"), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def test_guest_one_tap_and_private_status():
    client, _ = client_with_db()
    try:
        response = client.post("/api/v1/medical-alerts", json={"source": "self"},
                               headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440000"})
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "new"
        assert data["identity_verified"] is False
        assert data["guest_token"]
        assert response.json()["id"] == client.post(
            "/api/v1/medical-alerts", json={"source": "self"},
            headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440000"}
        ).json()["id"]
        assert client.get(f"/api/v1/medical-alerts/{data['id']}/public").status_code == 403
        status = client.get(f"/api/v1/medical-alerts/{data['id']}/public",
                            headers={"X-Alert-Token": data["guest_token"]})
        assert status.status_code == 200
        assert status.json()["status"] == "new"
    finally:
        app.dependency_overrides.clear()


def test_admin_claim_staff_handoff_and_guest_location():
    client, maker = client_with_db()
    admin_id = add_user(maker, "admin@example.edu", Role.admin)
    staff_id = add_user(maker, "staff@example.edu", Role.responder)
    try:
        created = client.post("/api/v1/medical-alerts", json={"source": "bystander"},
                              headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440001"}).json()
        alert_id = created["id"]
        assert client.patch(f"/api/v1/medical-alerts/{alert_id}/location",
                            json={"place_name": "Library", "location_text": "Ground floor"},
                            headers={"X-Alert-Token": created["guest_token"]}).status_code == 200
        assert client.get("/api/v1/medical-alerts/admin/queue", headers=auth(staff_id)).status_code == 403
        assert client.post(f"/api/v1/medical-alerts/{alert_id}/claim", headers=auth(admin_id)).status_code == 200
        assert client.post(f"/api/v1/medical-alerts/{alert_id}/claim", headers=auth(staff_id)).status_code == 403
        assert client.post(f"/api/v1/medical-alerts/{alert_id}/staff",
                           json={"user_id": staff_id}, headers=auth(admin_id)).status_code == 200
        inbox = client.get("/api/v1/medical-alerts/staff/inbox", headers=auth(staff_id))
        assert inbox.status_code == 200
        assert inbox.json()[0]["id"] == alert_id
        assert client.post(f"/api/v1/medical-alerts/{alert_id}/staff/acknowledge",
                           headers=auth(staff_id)).status_code == 200
        assert client.get("/api/v1/medical-alerts/staff/inbox", headers=auth(staff_id)).json()[0]["assignment_status"] == "acknowledged"
        assert client.get("/api/v1/medical-alerts/admin/queue", headers=auth(admin_id)).json()[0]["location_text"] == "Ground floor"
    finally:
        app.dependency_overrides.clear()


def test_false_report_requires_reason_and_never_follows_silence():
    client, maker = client_with_db()
    admin_id = add_user(maker, "admin2@example.edu", Role.admin)
    try:
        alert_id = client.post("/api/v1/medical-alerts", json={"source": "self"},
                               headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440002"}).json()["id"]
        assert client.post(f"/api/v1/medical-alerts/{alert_id}/close-false",
                           json={"reason": ""}, headers=auth(admin_id)).status_code == 422
        assert client.get("/api/v1/medical-alerts/admin/queue", headers=auth(admin_id)).json()[0]["status"] == "new"
    finally:
        app.dependency_overrides.clear()


def test_home_prioritizes_medical_help_without_sign_in():
    client, _ = client_with_db()
    try:
        response = client.get("/")
        assert response.status_code == 200
        assert "Get medical help" in response.text
        assert "Report someone else's emergency" in response.text
    finally:
        app.dependency_overrides.clear()


def test_guest_status_token_expires():
    client, maker = client_with_db()
    try:
        created = client.post("/api/v1/medical-alerts", json={"source": "self"},
                              headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440003"}).json()
        with maker() as db:
            alert = db.get(MedicalAlert, created["id"])
            alert.guest_token_expires_at = utc_now() - timedelta(seconds=1)
            db.commit()
        response = client.get(f"/api/v1/medical-alerts/{created['id']}/public",
                              headers={"X-Alert-Token": created["guest_token"]})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_admin_can_change_contact_shift_and_availability():
    client, maker = client_with_db()
    admin_id = add_user(maker, "shiftadmin@example.edu", Role.admin)
    try:
        created = client.post("/api/v1/campus/contacts", headers=auth(admin_id), json={
            "name": "Library caretaker", "kind": "caretaker", "phone": "1234567890",
            "shift": "day"
        })
        assert created.status_code == 201, created.text
        contact_id = created.json()["id"]
        updated = client.patch(f"/api/v1/campus/contacts/{contact_id}",
                               headers=auth(admin_id), json={
                                   "phone": None, "shift": "night", "active": False
                               })
        assert updated.status_code == 200, updated.text
        assert updated.json()["phone"] is None
        assert updated.json()["shift"] == "night"
        assert updated.json()["active"] is False
        assert client.patch(f"/api/v1/campus/contacts/{contact_id}",
                            headers=auth(admin_id), json={"shift": None}).status_code == 422
    finally:
        app.dependency_overrides.clear()
