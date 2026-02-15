import aws_cdk as cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    aws_secretsmanager as secretsmanager,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_iam as iam,
    Duration,
    RemovalPolicy,
)
from constructs import Construct


class IncidentIQStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ─────────────────────────────────────────────────────────────
        # S3 — Object storage for payloads, snapshots, postmortems
        # ─────────────────────────────────────────────────────────────
        self.bucket = s3.Bucket(
            self, "IncidentIQBucket",
            bucket_name=f"incidentiq-{self.account}-{self.region}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-replays",
                    prefix="replay-blobs/",
                    expiration=Duration.days(90),
                )
            ],
        )

        # ─────────────────────────────────────────────────────────────
        # DynamoDB — Incident state store
        # ─────────────────────────────────────────────────────────────
        self.incidents_table = dynamodb.Table(
            self, "IncidentsTable",
            table_name="incidentiq-incidents",
            partition_key=dynamodb.Attribute(
                name="incident_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for querying by status (dashboard polling)
        self.incidents_table.add_global_secondary_index(
            index_name="status-created-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ─────────────────────────────────────────────────────────────
        # SQS — Incident ingest queue with DLQ
        # ─────────────────────────────────────────────────────────────
        self.dlq = sqs.Queue(
            self, "IncidentDLQ",
            queue_name="incidentiq-dlq",
            retention_period=Duration.days(14),
        )

        self.ingest_queue = sqs.Queue(
            self, "IncidentIngestQueue",
            queue_name="incidentiq-ingest",
            visibility_timeout=Duration.minutes(15),  # must be >= Lambda timeout
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.dlq,
            ),
        )

        # ─────────────────────────────────────────────────────────────
        # SNS — Alert fan-out topic
        # ─────────────────────────────────────────────────────────────
        self.alert_topic = sns.Topic(
            self, "AlertTopic",
            topic_name="incidentiq-alerts",
            display_name="IncidentIQ Alert Notifications",
        )

        # Wire SNS → SQS
        self.alert_topic.add_subscription(
            sns_subs.SqsSubscription(
                self.ingest_queue,
                raw_message_delivery=True,
            )
        )

        # ─────────────────────────────────────────────────────────────
        # Secrets Manager — API credentials
        # ─────────────────────────────────────────────────────────────
        self.github_secret = secretsmanager.Secret(
            self, "GitHubSecret",
            secret_name="incidentiq/github-token",
            description="GitHub personal access token for commit queries",
        )

        self.slack_secret = secretsmanager.Secret(
            self, "SlackSecret",
            secret_name="incidentiq/slack-webhook",
            description="Slack webhook URL for war-room brief posting",
        )

        # ─────────────────────────────────────────────────────────────
        # IAM Role — Backend + Lambda permissions
        # ─────────────────────────────────────────────────────────────
        self.backend_role = iam.Role(
            self, "BackendRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name="incidentiq-backend-role",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # DynamoDB access
        self.incidents_table.grant_read_write_data(self.backend_role)

        # S3 access
        self.bucket.grant_read_write(self.backend_role)

        # SQS access
        self.ingest_queue.grant_consume_messages(self.backend_role)

        # Secrets access
        self.github_secret.grant_read(self.backend_role)
        self.slack_secret.grant_read(self.backend_role)

        # Bedrock access — Nova 2 Lite + Embeddings
        self.backend_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                ],
                resources=["*"],  # Tighten to specific model ARNs in production
            )
        )

        # CloudWatch access (for metric queries from agents)
        self.backend_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                    "cloudwatch:DescribeAlarms",
                ],
                resources=["*"],
            )
        )

        # ─────────────────────────────────────────────────────────────
        # Lambda — Ingest handler (CloudWatch → SQS → Lambda)
        # ─────────────────────────────────────────────────────────────
        self.ingest_lambda = lambda_.Function(
            self, "IngestHandler",
            function_name="incidentiq-ingest",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="ingest_handler.handler",
            code=lambda_.Code.from_asset("../backend/lambda"),
            role=self.backend_role,
            timeout=Duration.minutes(14),
            memory_size=512,
            environment={
                "INCIDENTS_TABLE": self.incidents_table.table_name,
                "S3_BUCKET": self.bucket.bucket_name,
                "ORCHESTRATOR_URL": "http://localhost:8000",  # Update for prod
            },
        )

        # Wire SQS → Lambda
        self.ingest_lambda.add_event_source(
            lambda_events.SqsEventSource(
                self.ingest_queue,
                batch_size=1,  # Process one incident at a time
                report_batch_item_failures=True,
            )
        )

        # ─────────────────────────────────────────────────────────────
        # CloudWatch Alarm — Demo alarm (payments service error rate)
        # ─────────────────────────────────────────────────────────────
        demo_alarm = cloudwatch.Alarm(
            self, "PaymentsErrorRateAlarm",
            alarm_name="incidentiq-demo-payments-error-rate",
            alarm_description="Demo alarm: payments-service 5xx error rate spike",
            metric=cloudwatch.Metric(
                namespace="IncidentIQ/Demo",
                metric_name="ErrorRate",
                dimensions_map={"Service": "payments-service"},
                statistic="Average",
                period=Duration.minutes(1),
            ),
            threshold=5.0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Wire alarm → SNS topic
        demo_alarm.add_alarm_action(
            cw_actions.SnsAction(self.alert_topic)
        )

        # ─────────────────────────────────────────────────────────────
        # Outputs — Print resource names after deploy
        # ─────────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "IncidentsTableName",
            value=self.incidents_table.table_name,
            description="DynamoDB incidents table name",
        )
        cdk.CfnOutput(self, "S3BucketName",
            value=self.bucket.bucket_name,
            description="S3 bucket for incident artifacts",
        )
        cdk.CfnOutput(self, "IngestQueueUrl",
            value=self.ingest_queue.queue_url,
            description="SQS ingest queue URL",
        )
        cdk.CfnOutput(self, "AlertTopicArn",
            value=self.alert_topic.topic_arn,
            description="SNS alert topic ARN",
        )
        cdk.CfnOutput(self, "GitHubSecretArn",
            value=self.github_secret.secret_arn,
            description="GitHub token secret ARN — set value in console",
        )
        cdk.CfnOutput(self, "SlackSecretArn",
            value=self.slack_secret.secret_arn,
            description="Slack webhook secret ARN — set value in console",
        )


app = cdk.App()
IncidentIQStack(app, "IncidentIQStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    )
)
app.synth()
