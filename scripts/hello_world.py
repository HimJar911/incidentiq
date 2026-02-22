#!/usr/bin/env python3
"""
Day 1 sanity check — verify your entire stack talks to each other.

Run this FIRST before building anything. If this script works end-to-end,
you're ready to build Week 1.

Checks:
  1. AWS credentials valid
  2. DynamoDB table exists + readable
  3. S3 bucket exists + writable
  4. Bedrock (Nova 2 Lite) reachable + responsive
  5. Strands Agents can invoke Nova 2 Lite

Usage:
    cd backend
    pip install -r requirements.txt
    python ../scripts/hello_world.py
"""
import json
import os
import sys
import boto3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
except ImportError:
    pass

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("INCIDENTS_TABLE", "incidentiq-incidents")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"


def check(label: str, fn):
    """Run a check and print pass/fail."""
    try:
        result = fn()
        print(f"  ✅ {label}")
        if result:
            print(f"     {result}")
        return True
    except Exception as e:
        print(f"  ❌ {label}")
        print(f"     Error: {e}")
        return False


def main():
    print("🚀 IncidentIQ — Stack Verification")
    print("=" * 50)
    all_passed = True

    # ── 1. AWS Credentials ───────────────────────────────────────────────────
    print("\n[1/5] AWS Credentials")
    passed = check(
        "AWS credentials valid",
        lambda: boto3.client("sts", region_name=AWS_REGION)
                      .get_caller_identity()["Account"]
    )
    all_passed = all_passed and passed

    # ── 2. DynamoDB ──────────────────────────────────────────────────────────
    print("\n[2/5] DynamoDB")
    def check_dynamo():
        ddb = boto3.client("dynamodb", region_name=AWS_REGION)
        response = ddb.describe_table(TableName=TABLE_NAME)
        status = response["Table"]["TableStatus"]
        return f"Table '{TABLE_NAME}' status: {status}"

    passed = check("DynamoDB table accessible", check_dynamo)
    all_passed = all_passed and passed

    # ── 3. S3 ────────────────────────────────────────────────────────────────
    print("\n[3/5] S3")
    def check_s3():
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET not set in .env — set it after CDK deploy")
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.put_object(
            Bucket=S3_BUCKET,
            Key="health-check/test.txt",
            Body=b"incidentiq health check",
        )
        return f"Wrote to s3://{S3_BUCKET}/health-check/test.txt"

    passed = check("S3 bucket writable", check_s3)
    all_passed = all_passed and passed

    # ── 4. Nova 2 Lite (direct Bedrock call) ─────────────────────────────────
    print("\n[4/5] Amazon Nova 2 Lite (Bedrock)")
    def check_nova():
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        response = bedrock.invoke_model(
    modelId=NOVA_LITE_MODEL,
    body=json.dumps({
        "messages": [
            {"role": "user", "content": [{"text": "Reply with exactly: INCIDENTIQ_READY"}]}
        ],
        "inferenceConfig": {"maxTokens": 16, "temperature": 0.0},
    }),
    contentType="application/json",
    accept="application/json",
)

        body = json.loads(response["body"].read())
        reply = body["output"]["message"]["content"][0]["text"].strip()
        return f"Nova 2 Lite replied: '{reply}'"

    passed = check("Nova 2 Lite reachable", check_nova)
    all_passed = all_passed and passed

    # ── 5. Strands Agents ────────────────────────────────────────────────────
    print("\n[5/5] Strands Agents")
    def check_strands():
        try:
            from strands import Agent
            from strands.models import BedrockModel

            model = BedrockModel(
                model_id=NOVA_LITE_MODEL,
                region_name=AWS_REGION,
            )
            agent = Agent(model=model)
            response = agent("Reply with exactly: STRANDS_READY")
            # Extract text from response
            reply = str(response).strip()[:50]
            return f"Strands Agent replied: '{reply}'"
        except ImportError:
            raise ImportError("strands-agents not installed — run: pip install strands-agents")

    passed = check("Strands Agents + Nova 2 Lite", check_strands)
    all_passed = all_passed and passed

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    if all_passed:
        print("✅ All checks passed — you're ready to build!")
        print("\nNext steps:")
        print("  1. Start the API:  uvicorn backend.api.main:app --reload")
        print("  2. Fire a test:    curl -X POST http://localhost:8000/api/replay")
        print("  3. Build Week 1:   CloudWatch → SNS → SQS → Lambda trigger")
    else:
        print("❌ Some checks failed — fix errors above before building")
        print("\nCommon fixes:")
        print("  - AWS credentials: run 'aws configure'")
        print("  - Missing resources: run 'cd infra && cdk deploy'")
        print("  - Bedrock access: enable Nova 2 Lite in AWS Console → Bedrock → Model Access")
        sys.exit(1)


if __name__ == "__main__":
    main()
