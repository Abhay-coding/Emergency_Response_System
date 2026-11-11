from app.services.data_api import AuroraAlertRepository, AuroraUserRepository, DynamoIdempotencyLedger
from app.dynamo_demo_repository import DynamoDemoRepository


class FakeTable:
    def __init__(self): self.items = {}
    def put_item(self, *, Item, **_):
        if Item["request_key"] in self.items: raise RuntimeError("exists")
        self.items[Item["request_key"]] = Item
    def get_item(self, *, Key): return {"Item": self.items.get(Key["request_key"])} if Key["request_key"] in self.items else {}
    def update_item(self, *, Key, ExpressionAttributeValues, **_):
        self.items[Key["request_key"]].update(state=ExpressionAttributeValues[":completed"], alert_id=ExpressionAttributeValues[":alert_id"])


class FakeDataApi:
    def __init__(self): self.calls = []
    def begin_transaction(self, **kwargs): self.calls.append(("begin", kwargs)); return {"transactionId": "tx-1"}
    def execute_statement(self, **kwargs):
        self.calls.append(("statement", kwargs))
        if "FROM users" in kwargs["sql"]:
            return {"records": [[
                {"longValue": 7}, {"stringValue": "Demo Admin"},
                {"stringValue": "admin@example.edu"}, {"stringValue": "hash"},
                {"stringValue": "admin"}, {"booleanValue": False},
            ]]}
        return {"records": [[{"longValue": 42}]]} if "RETURNING id" in kwargs["sql"] else {}
    def commit_transaction(self, **kwargs): self.calls.append(("commit", kwargs)); return {}
    def rollback_transaction(self, **kwargs): self.calls.append(("rollback", kwargs)); return {}


def test_ledger_claim_then_completed_result():
    ledger = DynamoIdempotencyLedger(FakeTable())
    assert ledger.claim("key-1").state == "claimed"
    ledger.complete("key-1", 42)
    result = ledger.claim("key-1")
    assert result.state == "completed"
    assert result.alert_id == 42


def test_alert_and_audit_share_one_data_api_transaction():
    client = FakeDataApi()
    repository = AuroraAlertRepository(client, "cluster", "secret", "campus")
    assert repository.create_alert(idempotency_key="key-1", source="self") == 42
    assert [call[0] for call in client.calls] == ["begin", "statement", "statement", "commit"]
    transaction_ids = [call[1].get("transactionId") for call in client.calls[1:-1]]
    assert transaction_ids == ["tx-1", "tx-1"]


def test_user_lookup_maps_data_api_record():
    user = AuroraUserRepository(FakeDataApi(), "cluster", "secret", "campus").find_by_email("ADMIN@example.edu")
    assert user == {"id": 7, "name": "Demo Admin", "email": "admin@example.edu", "password_hash": "hash", "role": "admin", "must_reset_password": False}


class FakeDynamoAlertTable:
    def __init__(self):
        self.item = {"pk": "ALERT#1", "sk": "META", "id": 1, "version": 1}
        self.update_kwargs = None
        self.name = "demo-test"
        self.meta = type("Meta", (), {"client": self})()

    def transact_write_items(self, *, TransactItems):
        self.update_kwargs = TransactItems[0]["Update"]
        self.item["version"] += 1

    def update_item(self, **kwargs):
        self.update_kwargs = kwargs
        self.item["version"] += 1

    def get_item(self, **_):
        return {"Item": self.item}

    def put_item(self, **_):
        return {}


def test_dynamo_verify_does_not_send_unused_status_placeholder():
    repo = DynamoDemoRepository.__new__(DynamoDemoRepository)
    repo.table = FakeDynamoAlertTable()

    result = repo.conditional_action(
        1, 1, 1, verification="confirmed_need", action="need_confirmed"
    )

    assert result["version"] == 2
    assert "ExpressionAttributeNames" not in repo.table.update_kwargs


def test_demo_alerts_use_a_distinct_namespace():
    assert DynamoDemoRepository._pk(42) == "DEMO#ALERT#42"


def test_demo_defaults_seed_once_per_process_and_retry_failure(monkeypatch):
    import app.dynamo_demo_repository as module
    import pytest
    class Client:
        meta = type("ClientMeta", (), {"endpoint_url":"http://local-test"})()
    class Table:
        name = "seed-once-test"
        meta = type("TableMeta", (), {"client":Client()})()
    class Resource:
        def Table(self, _): return Table()
    calls=[]
    def seed(_):
        calls.append(1)
        if len(calls) == 1: raise RuntimeError("temporary failure")
    monkeypatch.setattr(module.boto3,"resource",lambda _: Resource())
    monkeypatch.setattr(DynamoDemoRepository,"_seed",seed)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_SECRET_ARN",raising=False)
    monkeypatch.setattr(module,"_seeded_tables",set())
    with pytest.raises(RuntimeError): DynamoDemoRepository(table_name="seed-once-test")
    DynamoDemoRepository(table_name="seed-once-test")
    DynamoDemoRepository(table_name="seed-once-test")
    assert len(calls) == 2


def test_device_coordinates_are_stored_as_dynamodb_numbers():
    from decimal import Decimal
    repo = DynamoDemoRepository.__new__(DynamoDemoRepository)
    repo.table = FakeDynamoAlertTable()
    repo.update_alert_details(1, latitude=28.5, longitude=77.2, accuracy_m=12.5)
    values = repo.table.update_kwargs["ExpressionAttributeValues"]
    assert values[":latitude"] == Decimal("28.5")
    assert values[":longitude"] == Decimal("77.2")
    assert values[":accuracy_m"] == Decimal("12.5")


def test_reset_only_deletes_demo_alert_partitions():
    class ResetTable:
        def __init__(self):
            self.items = [{"pk":"DEMO#ALERT#1","sk":"META"}, {"pk":"DEMO#ALERT#1","sk":"EVENT#1"}, {"pk":"ALERT#1","sk":"META"}, {"pk":"DEMO#CONTACT","sk":"001"}, {"pk":"USER#1","sk":"PROFILE"}]
            self.deleted = []
        def scan(self, **kwargs): return {"Items":self.items}
        def delete_item(self, *, Key): self.deleted.append(Key)
    repo=DynamoDemoRepository.__new__(DynamoDemoRepository)
    repo.table=ResetTable()
    assert repo.reset_demo_alerts() == 2
    assert all(item["pk"] == "DEMO#ALERT#1" for item in repo.table.deleted)


def test_demo_contact_result_waits_until_saved_deadline(monkeypatch):
    import app.dynamo_demo_repository as module
    class Table:
        def __init__(self):
            self.item={"pk":"DEMO#ALERT#1","sk":"META","id":1,"status":"contact_pending","version":2,"contact_due":110,"contact_outcome":"accepted","contact_name":"Demo team","contact_phone":"DEMO-001"}
            self.events=[]
            self.name="demo-test"
            self.meta=type("Meta", (), {"client":self})()
        def transact_write_items(self, *, TransactItems):
            self.update_item(**TransactItems[0]["Update"])
            self.put_item(**TransactItems[1]["Put"])
        def get_item(self, **kwargs): return {"Item":dict(self.item)}
        def update_item(self, **kwargs):
            self.item.update(status=kwargs["ExpressionAttributeValues"][":s"], version=self.item["version"]+1)
        def put_item(self, *, Item, **kwargs): self.events.append(Item)
    repo=DynamoDemoRepository.__new__(DynamoDemoRepository)
    repo.table=Table()
    monkeypatch.setattr(module.time,"time",lambda:100)
    assert repo.alert(1)["status"] == "contact_pending"
    assert repo.table.events == []
    monkeypatch.setattr(module.time,"time",lambda:111)
    assert repo.alert(1)["status"] == "staff_alerted"
    assert repo.table.events[0]["action"] == "demo_contact_result"
    assert repo.alert(1)["status"] == "staff_alerted"
    assert len(repo.table.events) == 1


def test_contact_update_aliases_dynamodb_reserved_names():
    class Table:
        def __init__(self): self.request=None
        def scan(self, **kwargs): return {"Items":[{"pk":"DEMO#CONTACT","sk":"001","id":1,"name":"Demo","active":True}]}
        def update_item(self, **kwargs): self.request=kwargs
    repo=DynamoDemoRepository.__new__(DynamoDemoRepository)
    repo.table=Table()
    repo.update_contact(1,name="Updated",outcome="no_answer")
    assert repo.table.request["ExpressionAttributeNames"]["#name"] == "name"
    assert "#name = :name" in repo.table.request["UpdateExpression"]


def test_alert_retry_repairs_creation_event_without_duplicate_alert():
    from botocore.exceptions import ClientError
    class Table:
        def __init__(self): self.items={}; self.fail_event=True
        def put_item(self, *, Item, **kwargs):
            key=(Item['pk'],Item['sk'])
            if key in self.items: raise ClientError({'Error':{'Code':'ConditionalCheckFailedException','Message':'exists'}},'PutItem')
            if Item['sk'].startswith('EVENT#') and self.fail_event:
                self.fail_event=False
                raise RuntimeError('interrupted before event')
            self.items[key]=Item.copy()
        def get_item(self, *, Key, **kwargs): return {'Item':self.items.get((Key['pk'],Key['sk']))}
    repo=DynamoDemoRepository.__new__(DynamoDemoRepository)
    repo.table=Table()
    import pytest
    with pytest.raises(RuntimeError):
        repo.create_alert(idempotency_key='request-1',source='self',guest_token_hash='hash')
    alert_id=repo.create_alert(idempotency_key='request-1',source='self',guest_token_hash='hash')
    assert repo.create_alert(idempotency_key='request-1',source='self',guest_token_hash='hash') == alert_id
    assert len(repo.table.items) == 2
    assert sum(item['sk']=='META' for item in repo.table.items.values()) == 1
