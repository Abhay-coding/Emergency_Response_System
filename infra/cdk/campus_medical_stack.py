"""Low-cost, Data-API based CDK stack.

This stack intentionally contains no VPC, RDS Proxy, SQS, SNS, or WAF.
"""

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
)
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct


class CampusMedicalDemoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        app_secret = secretsmanager.Secret(
            self,
            "ApplicationSecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template="{}",
                generate_string_key="jwt_secret",
                password_length=64,
                exclude_punctuation=True,
            ),
        )

        cluster = rds.CfnDBCluster(
            self,
            "AuroraCluster",
            engine="aurora-postgresql",
            database_name="campusmedical",
            manage_master_user_password=True,
            master_username="campusadmin",
            enable_http_endpoint=True,
            serverless_v2_scaling_configuration=rds.CfnDBCluster.ServerlessV2ScalingConfigurationProperty(
                min_capacity=0.0,
                max_capacity=1.0,
            ),
            deletion_protection=False,
            backup_retention_period=1,
        )
        instance = rds.CfnDBInstance(
            self,
            "AuroraWriter",
            db_cluster_identifier=cluster.ref,
            db_instance_class="db.serverless",
            engine="aurora-postgresql",
        )
        instance.add_dependency(cluster)

        ledger = dynamodb.Table(
            self,
            "IdempotencyLedger",
            partition_key=dynamodb.Attribute(
                name="request_key", type=dynamodb.AttributeType.STRING
            ),
            time_to_live_attribute="expires_at",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        function = lambda_.DockerImageFunction(
            self,
            "ApiFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                str(Path(__file__).resolve().parents[2]),
                file="Dockerfile.lambda",
            ),
            timeout=Duration.seconds(28),
            memory_size=1024,
            environment={
                "ENVIRONMENT": "production",
                "DATA_API_ENABLED": "true",
                "AURORA_CLUSTER_ARN": cluster.attr_db_cluster_arn,
                "AURORA_SECRET_ARN": cluster.attr_master_user_secret_secret_arn,
                "AURORA_DATABASE": "campusmedical",
                "IDEMPOTENCY_TABLE": ledger.table_name,
                "DATA_API_ENABLED": "true",
                "APP_SECRET_ARN": app_secret.secret_arn,
                "CORS_ORIGINS": "https://abhay-coding.github.io",
                "ALLOWED_HOSTS": "*",
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        ledger.grant_read_write_data(function)
        app_secret.grant_read(function)
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:BeginTransaction",
                    "rds-data:CommitTransaction",
                    "rds-data:RollbackTransaction",
                    "rds-data:ExecuteStatement",
                ],
                resources=[cluster.attr_db_cluster_arn],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[cluster.attr_master_user_secret_secret_arn],
            )
        )

        api = apigwv2.HttpApi(
            self,
            "HttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["https://abhay-coding.github.io"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Alert-Token"],
                max_age=Duration.hours(1),
            ),
        )
        api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=HttpLambdaIntegration("ApiIntegration", function),
        )

        CfnOutput(self, "ApiBaseUrl", value=api.api_endpoint)
        CfnOutput(self, "AuroraClusterArn", value=cluster.attr_db_cluster_arn)
