"""Run only against an explicitly configured in-memory local test database."""
import os
import uuid

import boto3
import pytest


@pytest.mark.skipif(not os.environ.get("DEMO_DYNAMODB_TEST_ENDPOINT"), reason="Local DynamoDB endpoint not configured")
def test_local_launcher_creates_demo_tables_and_preserves_admin(monkeypatch):
    import getpass
    import uvicorn
    from scripts import local_demo

    endpoint=os.environ["DEMO_DYNAMODB_TEST_ENDPOINT"]
    assert endpoint in {"http://127.0.0.1:18099", "http://localhost:18099", "http://127.0.0.1:8000"}
    suffix=uuid.uuid4().hex
    monkeypatch.setattr(local_demo,"LOCAL_ENDPOINT",endpoint)
    monkeypatch.setattr(local_demo,"DATA_TABLE","test_data_"+suffix)
    monkeypatch.setattr(local_demo,"LEDGER_TABLE","test_ledger_"+suffix)
    monkeypatch.setattr("builtins.input",lambda _: "local-admin@example.test")
    monkeypatch.setattr(getpass,"getpass",lambda _: "LocalPassword1!")
    launches=[]
    monkeypatch.setattr(uvicorn,"run",lambda *args, **kwargs: launches.append(kwargs))
    local_demo.main()
    db=boto3.resource("dynamodb",endpoint_url=endpoint,region_name="us-east-1",aws_access_key_id="local",aws_secret_access_key="local")
    table=db.Table(local_demo.DATA_TABLE)
    first=table.get_item(Key={"pk":"USER#1","sk":"PROFILE"},ConsistentRead=True)["Item"]
    monkeypatch.setattr("builtins.input",lambda _: pytest.fail("Existing admin must not be replaced"))
    local_demo.main()
    second=table.get_item(Key={"pk":"USER#1","sk":"PROFILE"},ConsistentRead=True)["Item"]
    assert first == second
    assert len(launches)==2 and all(run["host"]=="127.0.0.1" for run in launches)
    assert os.environ["AWS_ENDPOINT_URL"] == endpoint
    assert os.environ["NOTIFICATION_MODE"] == "simulation"
