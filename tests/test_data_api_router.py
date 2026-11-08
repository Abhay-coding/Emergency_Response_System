from app.core.security import hash_password, decode_access_token
from app.routers import data_api_demo


class FakeLedger:
    def __init__(self): self.items = {}
    def claim(self, key): return {"state":"completed", "alert_id":self.items[key]} if key in self.items else {"state":"claimed"}
    def complete(self, key, alert_id): self.items[key] = alert_id


class FakeRepo:
    def __init__(self):
        self.user = {"id":1,"name":"Admin","email":"admin@example.edu","password_hash":hash_password("Password1!"),"role":"admin","must_reset_password":False}
        self.alerts = {}; self.next_id = 1
    def find_user_by_email(self, email): return self.user if email == self.user["email"] else None
    def find_user(self, user_id): return {k:v for k,v in self.user.items() if k != "password_hash"} if user_id == 1 else None
    def places(self): return [{"id":1,"name":"Library","kind":"building"}]
    def create_alert(self, **_):
        alert_id=self.next_id; self.next_id += 1; self.alerts[alert_id] = {"id":alert_id,"status":"new","verification":"unverified","version":1}; return alert_id
    def queue(self): return list(self.alerts.values())
    def alert(self, alert_id): return self.alerts.get(alert_id)
    def events(self, _): return []
    def contacts(self): return []
    def register_student(self, name, email, password):
        if self.find_user_by_email(email): return None
        self.user = {"id": 2, "name": name, "email": email, "password_hash": hash_password(password), "role": "reporter", "must_reset_password": False}
        return self.user
    def place_by_name(self, name): return {"id": 1, "name": "Library"} if name == "Library" else None
    def update_alert_details(self, alert_id, **details):
        self.alerts[alert_id].update(details); self.alerts[alert_id]["version"] += 1
        return self.alerts[alert_id]
    def escalate_alert(self, alert_id):
        alert=self.alerts.get(alert_id)
        if alert: alert["escalated"] = True
        return alert
    def conditional_action(self, alert_id, version, _, **changes):
        alert=self.alerts.get(alert_id)
        if not alert or alert["version"] != version: return None
        alert.update({k:v for k,v in changes.items() if k in {"status","verification"} and v is not None}); alert["version"] += 1; return alert
    def assign_staff(self, alert_id, version, actor, staff_id): return self.conditional_action(alert_id,version,actor,status="staff_alerted",action="assigned")


def test_demo_alert_to_admin_resolution_flow():
    repo, claims = FakeRepo(), FakeLedger()
    token = data_api_demo.login("admin@example.edu", "Password1!", repo)["access_token"]
    admin = repo.find_user(int(decode_access_token(token)["sub"]))
    alert = data_api_demo.create_alert(data_api_demo.AlertIn(source="self"), "550e8400-e29b-41d4-a716-446655440000", None, repo, claims)
    alert_id = alert["id"]
    assert data_api_demo.create_alert(data_api_demo.AlertIn(source="self"), "550e8400-e29b-41d4-a716-446655440000", None, repo, claims)["id"] == alert_id
    claimed = data_api_demo.claim(alert_id, data_api_demo.ActionIn(version=1), admin, repo)
    assigned = data_api_demo.assign(alert_id, data_api_demo.AssignIn(version=claimed["version"], staff_id=1), admin, repo)
    assert assigned["notification"] == "demo_notification_recorded"
    assert data_api_demo.resolve(alert_id, data_api_demo.ActionIn(version=assigned["alert"]["version"]), admin, repo)["status"] == "resolved"


def test_student_registration_and_guest_detail_update():
    repo, claims = FakeRepo(), FakeLedger()
    created = data_api_demo.register(data_api_demo.RegisterIn(name="Student One", email="student@example.edu", password="Password1!"), repo)
    assert created["role"] == "reporter"
    alert = data_api_demo.create_alert(data_api_demo.AlertIn(source="self"), "550e8400-e29b-41d4-a716-446655440001", None, repo, claims)
    repo.alerts[alert["id"]]["guest_token_hash"] = data_api_demo.sha256(alert["guest_token"].encode()).hexdigest()
    updated = data_api_demo.update_details(alert["id"], data_api_demo.DetailsIn(place_name="Library", location_text="Ground floor"), alert["guest_token"], repo)
    assert updated["place_id"] == 1
    assert updated["location_text"] == "Ground floor"


def test_guest_can_request_urgent_follow_up_without_creating_a_duplicate_alert():
    repo, claims = FakeRepo(), FakeLedger()
    alert = data_api_demo.create_alert(data_api_demo.AlertIn(source="bystander"), "550e8400-e29b-41d4-a716-446655440002", None, repo, claims)
    repo.alerts[alert["id"]]["guest_token_hash"] = data_api_demo.sha256(alert["guest_token"].encode()).hexdigest()
    result = data_api_demo.escalate(alert["id"], alert["guest_token"], repo)
    assert result["id"] == alert["id"]
    assert result["escalated"] is True
