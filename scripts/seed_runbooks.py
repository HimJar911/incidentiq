#!/usr/bin/env python3
"""
Seed runbook documents into S3 for Bedrock Knowledge Base indexing.

Run this in Week 1, Day 5-6 after:
1. CDK stack is deployed (S3 bucket exists)
2. Bedrock Knowledge Base is created in the console
3. BEDROCK_KNOWLEDGE_BASE_ID is set in .env

Usage:
    cd scripts
    python seed_runbooks.py
"""
import boto3
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "backend" / ".env")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")
RUNBOOKS_DIR = Path(__file__).parent.parent / "runbooks"
S3_PREFIX = "runbooks/"


def upload_runbooks():
    """Upload all runbook markdown files to S3."""
    if not S3_BUCKET:
        print("❌ S3_BUCKET not set in .env")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=AWS_REGION)
    uploaded = 0

    print(f"📚 Uploading runbooks to s3://{S3_BUCKET}/{S3_PREFIX}")

    for runbook_file in RUNBOOKS_DIR.glob("*.md"):
        key = f"{S3_PREFIX}{runbook_file.name}"
        content = runbook_file.read_text(encoding="utf-8")

        # Extract metadata from frontmatter
        metadata = _parse_frontmatter(content)

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
            Metadata={k: str(v).encode('ascii', 'ignore').decode('ascii') for k, v in metadata.items()},
        )
        print(f"  ✅ {runbook_file.name} → {key}")
        uploaded += 1

    print(f"\n✅ Uploaded {uploaded} runbooks to S3")
    return uploaded


def trigger_knowledge_base_sync():
    """Trigger a Knowledge Base ingestion job to index new documents."""
    if not KNOWLEDGE_BASE_ID:
        print("\n⚠️  BEDROCK_KNOWLEDGE_BASE_ID not set — skipping KB sync")
        print("   After creating the KB in the AWS console, set the ID in .env")
        print("   and re-run this script to trigger indexing.")
        return

    bedrock_agent = boto3.client("bedrock-agent", region_name=AWS_REGION)

    # Get data source ID
    try:
        response = bedrock_agent.list_data_sources(knowledgeBaseId=KNOWLEDGE_BASE_ID)
        data_sources = response.get("dataSourceSummaries", [])

        if not data_sources:
            print("❌ No data sources found for Knowledge Base")
            return

        data_source_id = data_sources[0]["dataSourceId"]
        print(f"\n🔄 Triggering ingestion job for Knowledge Base {KNOWLEDGE_BASE_ID}")

        job_response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=data_source_id,
        )

        job_id = job_response["ingestionJob"]["ingestionJobId"]
        print(f"  ✅ Ingestion job started: {job_id}")
        print(f"  ℹ️  Check status in AWS Console → Bedrock → Knowledge Bases")

    except Exception as e:
        print(f"❌ Failed to trigger KB sync: {e}")


def verify_rag_query():
    """Test a sample RAG query against the Knowledge Base."""
    if not KNOWLEDGE_BASE_ID:
        print("\n⚠️  Skipping RAG verification — BEDROCK_KNOWLEDGE_BASE_ID not set")
        return

    print("\n🔍 Testing RAG query...")
    bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)

    test_query = "HIGH incident payments-service timeout error rate spike"

    try:
        response = bedrock_agent.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": test_query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 2,
                    "overrideSearchType": "SEMANTIC",
                }
            },
        )

        results = response.get("retrievalResults", [])
        print(f"  ✅ RAG query returned {len(results)} results")
        for i, result in enumerate(results):
            score = result.get("score", 0)
            snippet = result.get("content", {}).get("text", "")[:100]
            print(f"  [{i+1}] score={score:.3f} — {snippet}...")

    except Exception as e:
        print(f"  ❌ RAG query failed: {e}")
        print(f"  ℹ️  This is expected if the ingestion job hasn't completed yet")


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter metadata from runbook markdown."""
    metadata = {}
    if not content.startswith("---"):
        return metadata

    try:
        end = content.index("---", 3)
        frontmatter = content[3:end].strip()
        for line in frontmatter.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("[]").replace(", ", ",")
                if key in ("runbook_id", "title", "service", "first_action_step"):
                    metadata[key] = value
    except ValueError:
        pass

    return metadata


if __name__ == "__main__":
    print("🚀 IncidentIQ — Runbook Seeder")
    print("=" * 50)
    upload_runbooks()
    trigger_knowledge_base_sync()
    verify_rag_query()
    print("\n✅ Done. Check AWS Console for Knowledge Base indexing status.")
