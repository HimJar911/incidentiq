# IncidentIQ — Autonomous Incident Response Agent
> Amazon Nova AI Hackathon 2026 — Agentic AI Category

## What It Does
When a CloudWatch alarm fires, IncidentIQ autonomously:
1. **Triages** the incident — severity, blast radius, affected services
2. **Investigates** — fingers the suspect commit/PR from GitHub
3. **Searches runbooks** — semantic RAG over your runbook library
4. **Posts a war-room brief** to Slack with estimated user impact
5. **Generates a postmortem** the moment the incident is resolved

Built with Strands Agents + Amazon Nova 2 Lite + Nova Multimodal Embeddings on AWS.

---

## Stack
| Layer | Technology |
|---|---|
| Agent Orchestration | Strands Agents |
| LLM Reasoning | Amazon Nova 2 Lite (Bedrock) |
| Embeddings / RAG | Amazon Nova Multimodal Embeddings (Bedrock Knowledge Base) |
| Incident State | DynamoDB |
| Object Storage | S3 |
| Queue / Reliability | SQS + DLQ |
| Secrets | AWS Secrets Manager |
| Trigger | CloudWatch → SNS → Lambda |
| Backend | FastAPI (Python) |
| Dashboard | React |

---

## Repo Structure
```
incidentiq/
├── infra/                  CDK stack — all AWS resources
├── backend/
│   ├── agents/             5 Strands sub-agents
│   ├── orchestrator/       Strands planner + dispatch logic
│   ├── integrations/       GitHub, Slack, CloudWatch clients
│   ├── models/             Incident data model + DynamoDB helpers
│   └── api/                FastAPI routes (ingest, replay, resolve)
├── dashboard/              React dashboard (live feed, replay, postmortem)
├── runbooks/               Sample runbook docs for Bedrock Knowledge Base
├── replay/                 Pre-recorded alarm payloads for deterministic demo
└── scripts/                Utility scripts (seed runbooks, test trigger, etc.)
```

---

## Quick Start

### Prerequisites
- AWS CLI configured with appropriate permissions
- Node.js 18+ (for CDK)
- Python 3.11+
- AWS CDK v2: `npm install -g aws-cdk`

### 1. Deploy Infrastructure
```bash
cd infra
pip install -r requirements.txt
cdk bootstrap    # first time only
cdk deploy
```

### 2. Start Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your values
uvicorn api.main:app --reload --port 8000
```

### 3. Start Dashboard
```bash
cd dashboard
npm install
npm start
```

### 4. Seed Runbooks into Bedrock Knowledge Base
```bash
cd scripts
python seed_runbooks.py
```

### 5. Fire a Test Incident
```bash
# Replay endpoint (deterministic demo trigger)
curl -X POST http://localhost:8000/api/replay \
  -H "Content-Type: application/json" \
  -d @replay/payments_service_high.json
```

---

## Demo Flow (3-minute video script)
1. `0:00–0:25` — Problem setup voiceover
2. `0:25–0:45` — Alarm trigger + status → ingested
3. `0:45–1:10` — Live agent feed: triage + blast radius
4. `1:10–1:35` — Suspect commit + runbook hit
5. `1:35–1:55` — Slack war-room brief with user impact count
6. `1:55–2:15` — Postmortem generated
7. `2:15–2:45` — Architecture diagram close
8. `2:45–3:00` — Closing card + #AmazonNova

---

## Hackathon Submission
- **Category:** Agentic AI
- **Nova Models Used:** Nova 2 Lite (reasoning), Nova Multimodal Embeddings (RAG)
- **Hashtag:** #AmazonNova
