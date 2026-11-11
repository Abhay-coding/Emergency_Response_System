from app.core.security import hash_password, decode_access_token
from app.routers import data_api_demo
import pytest
from fastapi import HTTPException


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
    def contacts(self): return [{"id":1,"name":"Demo Medical Centre","active":True}]
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
    def assign_staff(self, alert_id, version, actor, staff_id, method="notification"): return self.conditional_action(alert_id,version,actor,status="staff_alerted",action="assigned")


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
    assert data_api_demo.resolve(alert_id, data_api_demo.ActionIn(version=assigned["alert"]["version"], note="Demo complete"), admin, repo)["status"] == "resolved"


def test_closed_alert_cannot_be_reopened_by_claim():
    repo=FakeRepo()
    repo.alerts[1]={"id":1,"status":"resolved","version":2}
    with pytest.raises(HTTPException) as error:
        data_api_demo.claim(1,data_api_demo.ActionIn(version=2),repo.find_user(1),repo)
    assert error.value.status_code == 409


@pytest.mark.parametrize('status',['contact_pending','staff_alerted','medical_dispatched','en_route','arrived'])
def test_review_actions_cannot_move_progressed_alert_backwards(status):
    repo=FakeRepo(); repo.alerts[1]={'id':1,'status':status,'version':3}; admin=repo.find_user(1)
    for action in (data_api_demo.claim,data_api_demo.contact):
        with pytest.raises(HTTPException) as error:
            action(1,data_api_demo.ActionIn(version=3,note='Demo review'),admin,repo)
        assert error.value.status_code == 409


def test_admin_queue_does_not_expose_guest_tokens_or_internal_keys():
    repo=FakeRepo()
    repo.alerts[1]={"id":1,"status":"new","version":1,"guest_token_hash":"secret","idempotency_key":"key","pk":"DEMO#ALERT#1","sk":"META"}
    result=data_api_demo.queue(repo.find_user(1),repo)[0]
    assert result == {"id":1,"status":"new","version":1}


def test_public_config_only_advertises_isolated_demo_repository():
    repo=FakeRepo()
    assert data_api_demo.public_config(repo)['demo_mode'] is False
    repo.isolated_demo_mode=True
    assert data_api_demo.public_config(repo)['demo_mode'] is True


def test_reset_alert_has_distinct_missing_status_and_bad_token_stays_forbidden():
    repo=FakeRepo()
    with pytest.raises(HTTPException) as missing:
        data_api_demo.public_status(1,"old-token",repo)
    assert missing.value.status_code == 404
    repo.alerts[1]={"id":1,"guest_token_hash":"different"}
    with pytest.raises(HTTPException) as forbidden:
        data_api_demo.public_status(1,"wrong-token",repo)
    assert forbidden.value.status_code == 403


def test_student_history_contains_only_safe_demo_stages():
    repo=FakeRepo(); token='guest-token'
    repo.alerts[1]={'id':1,'status':'staff_alerted','guest_token_hash':data_api_demo.sha256(token.encode()).hexdigest()}
    repo.events=lambda _: [{'action':'created','created_at':'2026-01-01T00:00:00Z','note':'private'}, {'action':'demo_contact_result','created_at':'2026-01-01T00:01:00Z','note':'DEMO: Team (DEMO-001) — accepted. No call or message sent.'}, {'action':'verification_suspected_false','note':'sensitive review'}]
    result=data_api_demo.public_status(1,token,repo)
    assert result['history']==[{'stage':'new','created_at':'2026-01-01T00:00:00Z'},{'stage':'staff','created_at':'2026-01-01T00:01:00Z'}]


def test_student_only_sees_an_accepted_demo_team():
    repo=FakeRepo(); token='guest-token'
    repo.alerts[1]={'id':1,'status':'checking','guest_token_hash':data_api_demo.sha256(token.encode()).hexdigest(),'contact_name':'Demo backup','contact_outcome':'no_answer'}
    assert data_api_demo.public_status(1,token,repo)['demo_team'] is None
    repo.alerts[1].update(status='medical_dispatched',contact_outcome='accepted')
    result=data_api_demo.public_status(1,token,repo)
    assert result['demo_team']=='Demo backup'
    assert 'contact_phone' not in result


def test_student_registration_and_guest_detail_update():
    repo, claims = FakeRepo(), FakeLedger()
    created = data_api_demo.register(data_api_demo.RegisterIn(name="Student One", email="student@example.edu", password="Password1!"), repo)
    assert created["role"] == "reporter"
    alert = data_api_demo.create_alert(data_api_demo.AlertIn(source="self"), "550e8400-e29b-41d4-a716-446655440001", None, repo, claims)
    repo.alerts[alert["id"]]["guest_token_hash"] = data_api_demo.sha256(alert["guest_token"].encode()).hexdigest()
    updated = data_api_demo.update_details(alert["id"], data_api_demo.DetailsIn(place_name="Library", location_text="Ground floor"), alert["guest_token"], repo)
    assert updated["place_id"] == 1
    assert updated["location_text"] == "Ground floor"


def test_rejects_incomplete_coordinate_pair():
    repo,claims=FakeRepo(),FakeLedger()
    alert=data_api_demo.create_alert(data_api_demo.AlertIn(),"550e8400-e29b-41d4-a716-446655440005",None,repo,claims)
    repo.alerts[alert['id']]['guest_token_hash']=data_api_demo.sha256(alert['guest_token'].encode()).hexdigest()
    with pytest.raises(HTTPException) as error:
        data_api_demo.update_details(alert['id'],data_api_demo.DetailsIn(latitude=28.5),alert['guest_token'],repo)
    assert error.value.status_code == 422


def test_guest_can_request_urgent_follow_up_without_creating_a_duplicate_alert():
    repo, claims = FakeRepo(), FakeLedger()
    alert = data_api_demo.create_alert(data_api_demo.AlertIn(source="bystander"), "550e8400-e29b-41d4-a716-446655440002", None, repo, claims)
    repo.alerts[alert["id"]]["guest_token_hash"] = data_api_demo.sha256(alert["guest_token"].encode()).hexdigest()
    result = data_api_demo.escalate(alert["id"], alert["guest_token"], repo)
    assert result["id"] == alert["id"]
    assert result["escalated"] is True


def test_demo_dispatch_requires_accepted_contact_and_progresses_in_order():
    repo, claims = FakeRepo(), FakeLedger()
    admin = repo.find_user(1)
    alert = data_api_demo.create_alert(data_api_demo.AlertIn(), "550e8400-e29b-41d4-a716-446655440003", None, repo, claims)
    alert_id = alert["id"]
    with pytest.raises(HTTPException) as error:
        data_api_demo.dispatch(alert_id, data_api_demo.ActionIn(version=1, note="Demo dispatch"), admin, repo)
    assert error.value.status_code == 409
    reviewed = data_api_demo.verify(alert_id, data_api_demo.ActionIn(version=1, note="Callback confirmed"), admin, repo)
    assigned = data_api_demo.assign(alert_id, data_api_demo.AssignIn(version=reviewed["version"], staff_id=1), admin, repo)["alert"]
    dispatched = data_api_demo.dispatch(alert_id, data_api_demo.ActionIn(version=assigned["version"], note="Demo dispatch"), admin, repo)
    for expected in ("en_route", "arrived", "resolved"):
        dispatched = data_api_demo.demo_progress(alert_id, data_api_demo.ActionIn(version=dispatched["version"], note="Demo completed"), admin, repo)
        assert dispatched["status"] == expected


def test_unverified_demo_can_dispatch_after_simulated_contact():
    repo=FakeRepo(); admin=repo.find_user(1)
    repo.alerts[1]={"id":1,"status":"staff_alerted","verification":"unverified","version":2}
    result=data_api_demo.dispatch(1,data_api_demo.ActionIn(version=2,note="Urgent demo dispatch"),admin,repo)
    assert result['status']=='medical_dispatched'


@pytest.mark.parametrize('note', [None, '', '  '])
def test_final_demo_resolution_requires_a_note(note):
    repo=FakeRepo(); admin=repo.find_user(1)
    repo.alerts[1]={'id':1,'status':'arrived','version':4}
    with pytest.raises(HTTPException) as error:
        data_api_demo.demo_progress(1,data_api_demo.ActionIn(version=4,note=note),admin,repo)
    assert error.value.status_code == 422
    assert repo.alerts[1]['status'] == 'arrived'


def test_false_report_closure_rejects_whitespace_reason():
    repo=FakeRepo(); admin=repo.find_user(1)
    repo.alerts[1]={'id':1,'status':'new','version':1}
    with pytest.raises(HTTPException) as error:
        data_api_demo.reject(1,data_api_demo.ActionIn(version=1,note='          '),admin,repo)
    assert error.value.status_code == 422
    assert repo.alerts[1]['status'] == 'new'


def test_verification_requires_notes_and_does_not_close_suspected_alert():
    repo=FakeRepo(); admin=repo.find_user(1)
    repo.alerts[1]={"id":1,"status":"new","verification":"unverified","version":1}
    with pytest.raises(HTTPException):
        data_api_demo.update_verification(1,data_api_demo.VerificationIn(version=1,verification='suspected_false'),admin,repo)
    updated=data_api_demo.update_verification(1,data_api_demo.VerificationIn(version=1,verification='suspected_false',note='Unable to confirm'),admin,repo)
    assert updated['verification']=='suspected_false' and updated['status']=='new'


@pytest.mark.parametrize('action', [data_api_demo.staff_acknowledged, data_api_demo.staff_findings])
def test_staff_notes_reject_a_concurrent_admin_update(action):
    repo = FakeRepo()
    repo.alerts[1] = {'id': 1, 'status': 'staff_alerted', 'version': 2}
    admin = repo.find_user(1)
    # Another admin has already advanced the version held by this caller.
    with pytest.raises(HTTPException) as error:
        action(1, data_api_demo.ActionIn(version=1, note='Demo response'), admin, repo)
    assert error.value.status_code == 409
    updated = action(1, data_api_demo.ActionIn(version=2, note='Demo response'), admin, repo)
    assert updated['version'] == 3


@pytest.mark.skipif(__import__('sys').platform == 'win32' and __import__('sys').version_info >= (3,14), reason='Starlette TestClient hangs with the local Windows Python 3.14 runtime; run in Python 3.11 Linux')
def test_http_guest_alert_admin_authorization_and_demo_dispatch():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    repo, claims = FakeRepo(), FakeLedger()
    application=FastAPI()
    application.include_router(data_api_demo.router, prefix="/api/v1")
    application.dependency_overrides[data_api_demo.get_repo]=lambda: repo
    application.dependency_overrides[data_api_demo.ledger]=lambda: claims
    client=TestClient(application)
    key="550e8400-e29b-41d4-a716-446655440099"
    created=client.post('/api/v1/medical-alerts',headers={'Idempotency-Key':key},json={'source':'bystander'})
    assert created.status_code == 201
    result=created.json(); alert_id=result['id']
    assert client.post('/api/v1/medical-alerts',headers={'Idempotency-Key':key},json={'source':'bystander'}).json()['id'] == alert_id
    repo.alerts[alert_id]['guest_token_hash']=data_api_demo.sha256(result['guest_token'].encode()).hexdigest()
    assert client.get('/api/v1/medical-alerts/admin/queue').status_code in (401,422)
    assert client.get(f'/api/v1/medical-alerts/{alert_id}/public',headers={'X-Alert-Token':'wrong'}).status_code == 403
    location=client.patch(f'/api/v1/medical-alerts/{alert_id}/location',headers={'X-Alert-Token':result['guest_token']},json={'place_name':'Library','location_text':'First floor'})
    assert location.status_code == 200 and location.json()['place_id'] == 1
    login=client.post('/api/v1/auth/login',data={'username':'admin@example.edu','password':'Password1!'})
    assert login.status_code == 200
    admin_headers={'Authorization':f"Bearer {login.json()['access_token']}"}
    queue=client.get('/api/v1/medical-alerts/admin/queue',headers=admin_headers)
    assert queue.status_code == 200 and queue.json()[0]['id'] == alert_id
    version=location.json()['version']
    verified=client.post(f'/api/v1/medical-alerts/{alert_id}/verify',headers=admin_headers,json={'version':version,'note':'Demo review'})
    assert verified.status_code == 200
    assigned=client.post(f'/api/v1/medical-alerts/{alert_id}/staff',headers=admin_headers,json={'version':verified.json()['version'],'staff_id':1,'method':'call'})
    assert assigned.status_code == 200
    dispatch=client.post(f'/api/v1/medical-alerts/{alert_id}/dispatch-medical',headers=admin_headers,json={'version':assigned.json()['alert']['version'],'note':'Demo dispatch'})
    assert dispatch.status_code == 200
    version=dispatch.json()['version']
    for status in ('en_route','arrived','resolved'):
        progress=client.post(f'/api/v1/medical-alerts/{alert_id}/demo-progress',headers=admin_headers,json={'version':version,'note':'Demo completed'})
        assert progress.status_code == 200 and progress.json()['status'] == status
        version=progress.json()['version']
    assert client.get(f'/api/v1/medical-alerts/{alert_id}/public',headers={'X-Alert-Token':result['guest_token']}).json()['status'] == 'resolved'
