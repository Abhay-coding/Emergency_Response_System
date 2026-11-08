"""Free-plan, pay-per-request campus medical demo infrastructure."""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2, aws_dynamodb as dynamodb
from aws_cdk import aws_ecr as ecr, aws_lambda as lambda_, aws_logs as logs, aws_secretsmanager as secretsmanager
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct


class CampusMedicalDemoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        secret = secretsmanager.Secret(self, "ApplicationSecret", generate_secret_string=secretsmanager.SecretStringGenerator(secret_string_template="{}", generate_string_key="jwt_secret", password_length=64, exclude_punctuation=True))
        admin = secretsmanager.Secret(self, "BootstrapAdmin", generate_secret_string=secretsmanager.SecretStringGenerator(secret_string_template='{"email":"admin123@gmail.com"}', generate_string_key="password", password_length=24, exclude_punctuation=True))
        data = dynamodb.Table(self, "DemoData", partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING), sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING), billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)
        ledger = dynamodb.Table(self, "IdempotencyLedger", partition_key=dynamodb.Attribute(name="request_key", type=dynamodb.AttributeType.STRING), time_to_live_attribute="expires_at", billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)
        image_repo = ecr.Repository.from_repository_name(self, "BootstrapImageRepository", f"cdk-hnb659fds-container-assets-{self.account}-{self.region}")
        fn = lambda_.DockerImageFunction(self, "ApiFunction", code=lambda_.DockerImageCode.from_ecr(image_repo, tag_or_digest="campus-medical-demo-v7"), timeout=Duration.seconds(28), memory_size=1024, log_retention=logs.RetentionDays.ONE_WEEK, environment={"ENVIRONMENT":"production", "DYNAMO_DEMO_ENABLED":"true", "DEMO_DATA_TABLE":data.table_name, "IDEMPOTENCY_TABLE":ledger.table_name, "APP_SECRET_ARN":secret.secret_arn, "BOOTSTRAP_ADMIN_SECRET_ARN":admin.secret_arn, "CORS_ORIGINS":"[\"https://abhay-coding.github.io\"]", "ALLOWED_HOSTS":"[\"*\"]"})
        data.grant_read_write_data(fn); ledger.grant_read_write_data(fn); secret.grant_read(fn); admin.grant_read(fn)
        api = apigwv2.HttpApi(self, "HttpApi", cors_preflight=apigwv2.CorsPreflightOptions(allow_origins=["https://abhay-coding.github.io"], allow_methods=[apigwv2.CorsHttpMethod.ANY], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Alert-Token"]))
        api.add_routes(path="/{proxy+}", methods=[apigwv2.HttpMethod.ANY], integration=HttpLambdaIntegration("ApiIntegration", fn))
        CfnOutput(self, "ApiBaseUrl", value=api.api_endpoint)
        CfnOutput(self, "BootstrapAdminSecretArn", value=admin.secret_arn)
