"""Run the isolated demo against DynamoDB Local, never an AWS endpoint.

Start DynamoDB Local on 127.0.0.1:18099 before running this module.
The tables are retained by the local database and are never deleted here.
"""
import getpass
import os
import secrets

LOCAL_ENDPOINT = "http://127.0.0.1:18099"
DATA_TABLE = "CampusMedicalLocalDemo"
LEDGER_TABLE = "CampusMedicalLocalLedger"


def main():
    # Isolate every SDK client used by this process, even if an AWS profile is
    # configured in the user's shell. Nothing is written to that profile.
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "local", "AWS_SECRET_ACCESS_KEY": "local",
        "AWS_DEFAULT_REGION": "us-east-1", "AWS_REGION": "us-east-1",
        "AWS_ENDPOINT_URL": LOCAL_ENDPOINT, "AWS_ENDPOINT_URL_DYNAMODB": LOCAL_ENDPOINT,
        "AWS_EC2_METADATA_DISABLED": "true", "ENVIRONMENT": "development",
        "DYNAMO_DEMO_ENABLED": "true", "DATA_API_ENABLED": "false",
        "NOTIFICATION_MODE": "simulation", "DEMO_DATA_TABLE": DATA_TABLE,
        "IDEMPOTENCY_TABLE": LEDGER_TABLE,
        "JWT_SECRET": secrets.token_urlsafe(48), "GUEST_TOKEN_SECRET": secrets.token_urlsafe(48),
    })
    for key in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "BOOTSTRAP_ADMIN_SECRET_ARN", "APP_SECRET_ARN"):
        os.environ.pop(key, None)

    import boto3
    from botocore.exceptions import ClientError
    from app.core.security import hash_password
    from app.dynamo_demo_repository import DynamoDemoRepository

    db=boto3.resource("dynamodb", endpoint_url=LOCAL_ENDPOINT, region_name="us-east-1", aws_access_key_id="local", aws_secret_access_key="local")
    for name, keys in ((DATA_TABLE, ("pk", "sk")), (LEDGER_TABLE, ("request_key",))):
        try:
            table=db.create_table(TableName=name,KeySchema=[{"AttributeName":key,"KeyType":"HASH" if i == 0 else "RANGE"} for i,key in enumerate(keys)],AttributeDefinitions=[{"AttributeName":key,"AttributeType":"S"} for key in keys],BillingMode="PAY_PER_REQUEST")
            table.wait_until_exists()
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceInUseException": raise
    table=db.Table(DATA_TABLE)
    if not table.get_item(Key={"pk":"USER#1","sk":"PROFILE"},ConsistentRead=True).get("Item"):
        email=input("Local demo admin email: ").strip().lower()
        password=getpass.getpass("Local demo admin password (at least 8 characters): ")
        if not email or len(password) < 8: raise ValueError("Provide an email and a password of at least 8 characters")
        try:
            table.put_item(Item={"pk":"USER#1","sk":"PROFILE","id":1,"name":"Local Demo Admin","email":email,"password_hash":hash_password(password),"role":"admin","must_reset_password":False},ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
    DynamoDemoRepository(table=table)
    print("Demo only: no real services will be contacted.")
    print("Open http://127.0.0.1:8000/?api_url=http://127.0.0.1:8000")
    print("Local sign-in sessions expire when this server restarts.")
    import uvicorn
    uvicorn.run("app.main:app",host="127.0.0.1",port=8000)


if __name__ == "__main__":
    main()
