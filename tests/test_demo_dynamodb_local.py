"""Optional integration test against an explicitly configured local DynamoDB."""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import boto3
import pytest
from botocore.exceptions import ClientError

from app.dynamo_demo_repository import DynamoDemoRepository


@pytest.mark.skipif(not os.environ.get("DEMO_DYNAMODB_TEST_ENDPOINT"), reason="Local DynamoDB endpoint not configured")
def test_demo_storage_lifecycle_against_dynamodb_local(monkeypatch):
    endpoint=os.environ["DEMO_DYNAMODB_TEST_ENDPOINT"]
    assert endpoint in {"http://127.0.0.1:18099", "http://localhost:18099", "http://127.0.0.1:8000"}
    db=boto3.resource("dynamodb",endpoint_url=endpoint,region_name="us-east-1",aws_access_key_id="local",aws_secret_access_key="local")
    table=db.create_table(TableName="test_"+uuid.uuid4().hex,KeySchema=[{"AttributeName":"pk","KeyType":"HASH"},{"AttributeName":"sk","KeyType":"RANGE"}],AttributeDefinitions=[{"AttributeName":"pk","AttributeType":"S"},{"AttributeName":"sk","AttributeType":"S"}],BillingMode="PAY_PER_REQUEST")
    table.wait_until_exists()
    monkeypatch.delenv("BOOTSTRAP_ADMIN_SECRET_ARN",raising=False)
    repo=DynamoDemoRepository(table=table)
    try:
        table.put_item(Item={"pk":"DEMO#CONTACT","sk":"001","id":1,"name":"Demo team","phone":"DEMO-001","active":True,"outcome":"accepted","delay_seconds":2,"kind":"medical","shift":"all"})
        table.put_item(Item={"pk":"ALERT#1","sk":"META","id":1,"status":"real"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            users=list(pool.map(lambda _: repo.register_student("Demo Student", "same@example.edu", "Password1!"), range(2)))
        assert sum(user is not None for user in users) == 1
        assert repo.find_user_by_email("SAME@example.edu")["id"] == next(user["id"] for user in users if user)
        alert_id=repo.create_alert(idempotency_key="local-test",source="self",guest_token_hash="hash")
        assert repo.create_alert(idempotency_key="local-test",source="self",guest_token_hash="hash") == alert_id
        updated=repo.update_alert_details(alert_id,latitude=28.5,longitude=77.2,accuracy_m=10.5)
        assert float(updated["latitude"]) == 28.5
        # If the activity entry cannot be written, the state change must not commit.
        table.put_item(Item={"pk":repo._pk(alert_id),"sk":"EVENT#123456789","action":"existing"})
        with monkeypatch.context() as patch:
            patch.setattr("app.dynamo_demo_repository.time.time_ns", lambda: 123456789)
            with pytest.raises(ClientError):
                repo.conditional_action(alert_id,updated["version"],1,verification="confirmed_need",action="verified",note="Demo")
        assert repo.alert(alert_id)["version"] == updated["version"]
        assert repo.alert(alert_id)["verification"] == "unverified"
        contact=repo.update_contact(1,name="Demo updated",delay_seconds=2)
        assert contact["name"] == "Demo updated"
        verified=repo.conditional_action(alert_id,updated["version"],1,verification="confirmed_need",action="verified",note="Demo")
        with monkeypatch.context() as patch:
            patch.setattr("app.dynamo_demo_repository.time.time_ns", lambda: 123456789)
            with pytest.raises(ClientError):
                repo.assign_staff(alert_id,verified["version"],1,1,"call")
        assert repo.alert(alert_id)["version"] == verified["version"]
        assert repo.alert(alert_id)["status"] == "new"
        pending=repo.assign_staff(alert_id,verified["version"],1,1,"call")
        assert pending["status"] == "contact_pending"
        time.sleep(3)
        with monkeypatch.context() as patch:
            patch.setattr("app.dynamo_demo_repository.time.time_ns", lambda: 123456789)
            with pytest.raises(ClientError):
                repo.alert(alert_id)
        assert table.get_item(Key={"pk":repo._pk(alert_id),"sk":"META"},ConsistentRead=True)["Item"]["status"] == "contact_pending"
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _: repo.alert(alert_id), range(4)))
        assert all(result["status"] == "staff_alerted" for result in results)
        assert [e["action"] for e in repo.events(alert_id)].count("demo_contact_result") == 1
        assert repo.reset_demo_alerts() >= 1
        assert table.get_item(Key={"pk":"ALERT#1","sk":"META"}).get("Item")["status"] == "real"
    finally:
        table.delete()


@pytest.mark.skipif(not os.environ.get("DEMO_DYNAMODB_TEST_ENDPOINT"), reason="Local DynamoDB endpoint not configured")
def test_http_workflow_against_dynamodb_local(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.security import hash_password
    from app.routers import data_api_demo

    endpoint=os.environ["DEMO_DYNAMODB_TEST_ENDPOINT"]
    assert endpoint in {"http://127.0.0.1:18099", "http://localhost:18099", "http://127.0.0.1:8000"}
    db=boto3.resource("dynamodb",endpoint_url=endpoint,region_name="us-east-1",aws_access_key_id="local",aws_secret_access_key="local")
    table=db.create_table(TableName="test_"+uuid.uuid4().hex,KeySchema=[{"AttributeName":"pk","KeyType":"HASH"},{"AttributeName":"sk","KeyType":"RANGE"}],AttributeDefinitions=[{"AttributeName":"pk","AttributeType":"S"},{"AttributeName":"sk","AttributeType":"S"}],BillingMode="PAY_PER_REQUEST")
    table.wait_until_exists()
    monkeypatch.delenv("BOOTSTRAP_ADMIN_SECRET_ARN",raising=False)
    repo=DynamoDemoRepository(table=table)
    class Ledger:
        def __init__(self): self.items={}
        def claim(self,key): return {"state":"completed","alert_id":self.items[key]} if key in self.items else {"state":"claimed"}
        def complete(self,key,alert_id): self.items[key]=alert_id
    ledger=Ledger()
    try:
        table.put_item(Item={"pk":"USER#1","sk":"PROFILE","id":1,"name":"Admin","email":"admin@example.edu","password_hash":hash_password("Password1!"),"role":"admin"})
        table.put_item(Item={"pk":"PLACE","sk":"001","id":1,"name":"Library","active":True})
        table.put_item(Item={"pk":"DEMO#CONTACT","sk":"001","id":1,"name":"Demo team","phone":"DEMO-001","active":True,"outcome":"no_answer","delay_seconds":0,"kind":"medical","shift":"all"})
        table.put_item(Item={"pk":"DEMO#CONTACT","sk":"002","id":2,"name":"Demo backup","phone":"DEMO-002","active":True,"outcome":"accepted","delay_seconds":0,"kind":"backup","shift":"all"})
        table.put_item(Item={"pk":"ALERT#123","sk":"META","id":123,"status":"real"})
        app=FastAPI(); app.include_router(data_api_demo.router,prefix="/api/v1")
        app.dependency_overrides[data_api_demo.get_repo]=lambda:repo
        app.dependency_overrides[data_api_demo.ledger]=lambda:ledger
        client=TestClient(app)
        registration=client.post('/api/v1/auth/register',json={'name':'Demo Student','email':'student@example.edu','password':'Password1!'})
        assert registration.status_code == 201, registration.text
        student_login=client.post('/api/v1/auth/login',data={'username':'student@example.edu','password':'Password1!'})
        assert student_login.status_code == 200, student_login.text
        student_headers={'Authorization':f"Bearer {student_login.json()['access_token']}",'Idempotency-Key':str(uuid.uuid4())}
        signed_alert=client.post('/api/v1/medical-alerts',headers=student_headers,json={'source':'self'})
        assert signed_alert.status_code == 201 and signed_alert.json()['identity_verified'] is True, signed_alert.text
        assert repo.alert(signed_alert.json()['id'])['reporter_id'] == registration.json()['id']
        key=str(uuid.uuid4())
        response=client.post('/api/v1/medical-alerts',headers={'Idempotency-Key':key},json={'source':'bystander'})
        assert response.status_code == 201, response.text
        alert=response.json(); alert_id=alert['id']; guest={'X-Alert-Token':alert['guest_token']}
        assert client.post('/api/v1/medical-alerts',headers={'Idempotency-Key':key},json={'source':'bystander'}).json()['id']==alert_id
        location=client.patch(f'/api/v1/medical-alerts/{alert_id}/location',headers=guest,json={'place_name':'Library','location_text':'First floor','latitude':28.5,'longitude':77.2,'accuracy_m':10.5})
        assert location.status_code == 200, location.text
        login=client.post('/api/v1/auth/login',data={'username':'admin@example.edu','password':'Password1!'})
        assert login.status_code == 200, login.text
        headers={'Authorization':f"Bearer {login.json()['access_token']}"}
        claim=client.post(f'/api/v1/medical-alerts/{alert_id}/claim',headers=headers,json={'version':location.json()['version']})
        assert claim.status_code == 200 and claim.json()['claimed_by'] == 1, claim.text
        stale=client.post(f'/api/v1/medical-alerts/{alert_id}/claim',headers=headers,json={'version':location.json()['version']})
        assert stale.status_code == 409, stale.text
        verify=client.post(f'/api/v1/medical-alerts/{alert_id}/verify',headers=headers,json={'version':claim.json()['version'],'note':'Demo verified'})
        assert verify.status_code == 200, verify.text
        first=client.post(f'/api/v1/medical-alerts/{alert_id}/staff',headers=headers,json={'version':verify.json()['version'],'staff_id':1,'method':'call'})
        assert first.status_code == 200 and first.json()['alert']['status']=='checking', first.text
        blocked=client.post(f'/api/v1/medical-alerts/{alert_id}/dispatch-medical',headers=headers,json={'version':first.json()['alert']['version'],'note':'Not yet'})
        assert blocked.status_code == 409, blocked.text
        assign=client.post(f'/api/v1/medical-alerts/{alert_id}/staff',headers=headers,json={'version':first.json()['alert']['version'],'staff_id':2,'method':'notification'})
        assert assign.status_code == 200 and assign.json()['alert']['status']=='staff_alerted', assign.text
        assert assign.json()['alert']['contact_id'] == 2
        assert next(a for a in client.get('/api/v1/medical-alerts/admin/queue',headers=headers).json() if a['id']==alert_id)['contact_id'] == 2
        assigned_version=assign.json()['alert']['version']
        findings=client.post(f'/api/v1/medical-alerts/{alert_id}/staff-findings',headers=headers,json={'version':assigned_version,'note':'Demo response noted'})
        assert findings.status_code == 200 and findings.json()['version'] == assigned_version + 1, findings.text
        stale=client.post(f'/api/v1/medical-alerts/{alert_id}/staff-acknowledged',headers=headers,json={'version':assigned_version,'note':'Stale response'})
        assert stale.status_code == 409, stale.text
        dispatch=client.post(f'/api/v1/medical-alerts/{alert_id}/dispatch-medical',headers=headers,json={'version':findings.json()['version'],'note':'Demo dispatch'})
        assert dispatch.status_code == 200, dispatch.text
        version=dispatch.json()['version']
        for expected in ('en_route','arrived','resolved'):
            if expected == 'resolved':
                missing=client.post(f'/api/v1/medical-alerts/{alert_id}/demo-progress',headers=headers,json={'version':version})
                assert missing.status_code == 422, missing.text
            progress=client.post(f'/api/v1/medical-alerts/{alert_id}/demo-progress',headers=headers,json={'version':version,'note':'Demo resolution'})
            assert progress.status_code == 200 and progress.json()['status']==expected, progress.text
            version=progress.json()['version']
        events=client.get(f'/api/v1/medical-alerts/{alert_id}/events',headers=headers).json()
        assert {'created','demo_contact_attempt','demo_contact_result','demo_medical_dispatched','demo_resolved'} <= {event['action'] for event in events}
        assert all(event['actor_id'] == 1 and event['created_at'] for event in events if event['action'] in {'claimed','need_confirmed','demo_medical_dispatched','demo_resolved'})
        assert any('no answer' in (event.get('note') or '') for event in events)
        public=client.get(f'/api/v1/medical-alerts/{alert_id}/public',headers=guest).json()
        assert public['status']=='resolved'
        assert [entry['stage'] for entry in public['history']] == ['new','acknowledged','staff','medical','en-route','arrived','resolved']
        assert all(entry.get('created_at') for entry in public['history'])
        assert client.get(f'/api/v1/medical-alerts/{alert_id}/public',headers=guest).json()['history'] == public['history']
        assert client.post('/api/v1/demo/reset',headers=headers).status_code == 200
        assert client.get(f'/api/v1/medical-alerts/{alert_id}/public',headers=guest).status_code == 404
        assert table.get_item(Key={'pk':'ALERT#123','sk':'META'})['Item']['status']=='real'
    finally:
        table.delete()
