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
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_ecr as ecr,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
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
            self,
            "IncidentIQBucket",
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
            self,
            "IncidentsTable",
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
        self.repos_table = dynamodb.Table(
            self,
            "ReposTable",
            table_name="incidentiq-repos",
            partition_key=dynamodb.Attribute(
                name="repo_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
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
            self,
            "IncidentDLQ",
            queue_name="incidentiq-dlq",
            retention_period=Duration.days(14),
        )

        self.ingest_queue = sqs.Queue(
            self,
            "IncidentIngestQueue",
            queue_name="incidentiq-ingest",
            visibility_timeout=Duration.minutes(15),
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
            self,
            "AlertTopic",
            topic_name="incidentiq-alerts",
            display_name="IncidentIQ Alert Notifications",
        )

        self.alert_topic.add_subscription(
            sns_subs.SqsSubscription(
                self.ingest_queue,
                raw_message_delivery=True,
            )
        )

        # ─────────────────────────────────────────────────────────────
        # Secrets Manager — API credentials
        # ─────────────────────────────────────────────────────────────
        self.github_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "GitHubSecret",
            secret_name="incidentiq/github-token",
        )

        self.slack_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "SlackSecret",
            secret_name="incidentiq/slack-webhook",
        )

        # ─────────────────────────────────────────────────────────────
        # VPC — Network for ECS Fargate
        # ─────────────────────────────────────────────────────────────
        self.vpc = ec2.Vpc(
            self,
            "IncidentIQVpc",
            vpc_name="incidentiq-vpc",
            max_azs=2,  # 2 AZs for ALB requirement
            nat_gateways=1,  # 1 NAT GW saves cost vs 2
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ─────────────────────────────────────────────────────────────
        # ECR — Docker image registry
        # ─────────────────────────────────────────────────────────────
        self.ecr_repo = ecr.Repository.from_repository_name(
            self,
            "BackendRepo",
            repository_name="incidentiq-backend",
        )

        # ─────────────────────────────────────────────────────────────
        # IAM Role — ECS Task (backend + agents)
        # ─────────────────────────────────────────────────────────────
        self.task_role = iam.Role(
            self,
            "EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name="incidentiq-ecs-task-role",
        )

        # DynamoDB
        self.incidents_table.grant_read_write_data(self.task_role)
        # Grant ECS task role read/write on repos table
        self.repos_table.grant_read_write_data(self.task_role)

        # S3
        self.bucket.grant_read_write(self.task_role)

        # Secrets Manager
        self.github_secret.grant_read(self.task_role)
        self.slack_secret.grant_read(self.task_role)

        # Bedrock
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                ],
                resources=["*"],
            )
        )

        # CloudWatch
        self.task_role.add_to_policy(
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
        # ECS Cluster
        # ─────────────────────────────────────────────────────────────
        self.cluster = ecs.Cluster(
            self,
            "IncidentIQCluster",
            cluster_name="incidentiq-cluster",
            vpc=self.vpc,
            container_insights=True,
        )

        # ─────────────────────────────────────────────────────────────
        # CloudWatch Log Group for Fargate
        # ─────────────────────────────────────────────────────────────
        self.log_group = logs.LogGroup(
            self,
            "BackendLogGroup",
            log_group_name="/incidentiq/backend",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ─────────────────────────────────────────────────────────────
        # ECS Fargate Task Definition
        # ─────────────────────────────────────────────────────────────
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "BackendTaskDef",
            family="incidentiq-backend",
            cpu=256,  # 0.25 vCPU — sufficient for FastAPI + agents
            memory_limit_mib=512,
            task_role=self.task_role,
        )

        self.container = self.task_definition.add_container(
            "BackendContainer",
            container_name="incidentiq-backend",
            image=ecs.ContainerImage.from_ecr_repository(
                self.ecr_repo,
                tag="latest",
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="backend",
                log_group=self.log_group,
            ),
            environment={
                "AWS_REGION": self.region,
                "INCIDENTS_TABLE": "incidentiq-incidents",
                "S3_BUCKET": f"incidentiq-{self.account}-{self.region}",
                "BEDROCK_KNOWLEDGE_BASE_ID": "JNLPFXJ80S",
                "GITHUB_ORG": "HimJar911",
                "GITHUB_REPO": "payments-service",
                "SLACK_CHANNEL": "#incidents",
                "REPOS_TABLE": "incidentiq-repos",
                "PUBLIC_URL": "http://incidentiq-alb-1884683334.us-east-1.elb.amazonaws.com",
                "GITHUB_WEBHOOK_SECRET": "incidentiq-webhook-secret",
                "VERIFY_WEBHOOK_SIGNATURE": "true",
                "COMMIT_LOOKBACK_HOURS": "168",
            },
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(30),
            ),
        )

        self.container.add_port_mappings(
            ecs.PortMapping(
                container_port=8000,
                protocol=ecs.Protocol.TCP,
            )
        )

        # ─────────────────────────────────────────────────────────────
        # Security Groups
        # ─────────────────────────────────────────────────────────────

        # ALB security group — accepts traffic from anywhere on port 80
        self.alb_sg = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=self.vpc,
            security_group_name="incidentiq-alb-sg",
            description="ALB security group - allows inbound HTTP",
            allow_all_outbound=True,
        )
        self.alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow HTTP from anywhere",
        )

        # Fargate security group — only accepts traffic from ALB
        self.fargate_sg = ec2.SecurityGroup(
            self,
            "FargateSecurityGroup",
            vpc=self.vpc,
            security_group_name="incidentiq-fargate-sg",
            description="Fargate task security group - allows traffic from ALB only",
            allow_all_outbound=True,
        )
        self.fargate_sg.add_ingress_rule(
            self.alb_sg,
            ec2.Port.tcp(8000),
            "Allow traffic from ALB on port 8000",
        )

        # ─────────────────────────────────────────────────────────────
        # Application Load Balancer
        # ─────────────────────────────────────────────────────────────
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "BackendALB",
            load_balancer_name="incidentiq-alb",
            vpc=self.vpc,
            internet_facing=True,  # Public — dashboard + Lambda reach it
            security_group=self.alb_sg,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC,
            ),
        )

        # Target group — points to Fargate tasks on port 8000
        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            "BackendTargetGroup",
            target_group_name="incidentiq-tg",
            vpc=self.vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )

        # HTTP listener on port 80
        self.listener = self.alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_target_groups=[self.target_group],
        )

        # ─────────────────────────────────────────────────────────────
        # ECS Fargate Service
        # ─────────────────────────────────────────────────────────────
        self.fargate_service = ecs.FargateService(
            self,
            "BackendService",
            service_name="incidentiq-backend",
            cluster=self.cluster,
            task_definition=self.task_definition,
            desired_count=1,
            security_groups=[self.fargate_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            assign_public_ip=False,  # Private subnet + NAT GW
            enable_execute_command=True,  # Allows ECS Exec for debugging
        )

        # Register Fargate service with target group
        self.fargate_service.attach_to_application_target_group(self.target_group)

        # ─────────────────────────────────────────────────────────────
        # IAM Role — Lambda Ingest Handler
        # ─────────────────────────────────────────────────────────────
        self.lambda_role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name="incidentiq-lambda-role",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        self.incidents_table.grant_read_write_data(self.lambda_role)
        self.bucket.grant_read_write(self.lambda_role)
        self.ingest_queue.grant_consume_messages(self.lambda_role)
        self.github_secret.grant_read(self.lambda_role)
        self.slack_secret.grant_read(self.lambda_role)

        # ─────────────────────────────────────────────────────────────
        # Lambda — Ingest handler
        # ─────────────────────────────────────────────────────────────
        self.ingest_lambda = lambda_.Function(
            self,
            "IngestHandler",
            function_name="incidentiq-ingest",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="ingest_handler.handler",
            code=lambda_.Code.from_asset("../backend/lambda"),
            role=self.lambda_role,
            timeout=Duration.minutes(14),
            memory_size=512,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            security_groups=[
                ec2.SecurityGroup(
                    self,
                    "LambdaSecurityGroup",
                    vpc=self.vpc,
                    security_group_name="incidentiq-lambda-sg",
                    description="Lambda security group",
                    allow_all_outbound=True,
                )
            ],
            environment={
                "INCIDENTS_TABLE": self.incidents_table.table_name,
                "S3_BUCKET": self.bucket.bucket_name,
                "ORCHESTRATOR_URL": f"http://{self.alb.load_balancer_dns_name}",
            },
        )

        # Wire SQS → Lambda
        self.ingest_lambda.add_event_source(
            lambda_events.SqsEventSource(
                self.ingest_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # Allow Lambda SG to reach ALB
        self.alb_sg.add_ingress_rule(
            self.ingest_lambda.connections.security_groups[0],
            ec2.Port.tcp(80),
            "Allow Lambda to reach ALB",
        )

        # ─────────────────────────────────────────────────────────────
        # CloudWatch Alarm — Demo alarm (payments service error rate)
        # ─────────────────────────────────────────────────────────────
        demo_alarm = cloudwatch.Alarm(
            self,
            "PaymentsErrorRateAlarm",
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

        demo_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # ─────────────────────────────────────────────────────────────
        # Outputs
        # ─────────────────────────────────────────────────────────────
        cdk.CfnOutput(
            self,
            "AlbDnsName",
            value=self.alb.load_balancer_dns_name,
            description="ALB DNS name — use this as ORCHESTRATOR_URL and for dashboard API calls",
        )
        cdk.CfnOutput(
            self,
            "EcrRepoUri",
            value=self.ecr_repo.repository_uri,
            description="ECR repository URI — push Docker image here",
        )
        cdk.CfnOutput(
            self,
            "IncidentsTableName",
            value=self.incidents_table.table_name,
            description="DynamoDB incidents table name",
        )
        cdk.CfnOutput(
            self,
            "S3BucketName",
            value=self.bucket.bucket_name,
            description="S3 bucket for incident artifacts",
        )
        cdk.CfnOutput(
            self,
            "IngestQueueUrl",
            value=self.ingest_queue.queue_url,
            description="SQS ingest queue URL",
        )
        cdk.CfnOutput(
            self,
            "AlertTopicArn",
            value=self.alert_topic.topic_arn,
            description="SNS alert topic ARN",
        )
        cdk.CfnOutput(
            self,
            "FargateServiceName",
            value=self.fargate_service.service_name,
            description="ECS Fargate service name",
        )
        cdk.CfnOutput(
            self,
            "ClusterName",
            value=self.cluster.cluster_name,
            description="ECS cluster name",
        )
        cdk.CfnOutput(
            self,
            "ReposTableName",
            value=self.repos_table.table_name,
            description="DynamoDB repos table — connected GitHub repos",
        )


app = cdk.App()
IncidentIQStack(
    app,
    "IncidentIQStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)
app.synth()
