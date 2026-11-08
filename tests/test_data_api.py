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
