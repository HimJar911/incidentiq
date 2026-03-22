# IncidentIQ
### Autonomous Incident Response, Powered by Amazon Nova

> When a bad commit hits production, IncidentIQ detects it in under 10 seconds, identifies the exact line that broke, knows how many users are affected, posts a Slack war room brief, and generates a full postmortem — all without a human touching anything.

**Live Demo:** [incidentiq-one.vercel.app](https://incidentiq-one.vercel.app)  
**Built for:** Amazon Nova AI Hackathon 2026

---

---

## Built With

- **Amazon Nova** (Lite, Pro, Multimodal Embeddings) via Amazon Bedrock
- **Amazon Bedrock Knowledge Bases** — semantic runbook search
- **AWS ECS Fargate** — containerized backend
- **AWS DynamoDB** — incident and repo state
- **AWS S3** — runbook storage
- **FastAPI** — backend API
- **React + Vite** — frontend dashboard
- **Vercel** — frontend hosting

---

## What It Does

Most incident response looks like this: an alert fires, an engineer gets paged at 2am, spends 20 minutes figuring out what broke and how bad it is, then another 30 minutes writing a postmortem from memory. IncidentIQ eliminates every one of those steps.

Connect a GitHub repo. Every push gets evaluated. The ones that matter trigger a full autonomous pipeline — triage, investigation, blast radius, Slack brief, and postmortem — in under 12 seconds.

---

## The Pipeline

When a risky commit is pushed to `main`:

```
GitHub Webhook
      ↓
Push Filter (2-layer gate)
  Layer 1: File pattern check — skip README edits, test changes, docs
  Layer 2: Nova Lite semantic risk check — is this worth paging on-call?
      ↓
Incident Created in DynamoDB
      ↓
5 Agents Run in Parallel:
  ├── Triage Agent       — classifies severity (LOW/MED/HIGH), calculates blast radius
  ├── Investigation Agent — fetches real unified diff from GitHub API, Nova reads actual changed lines
  ├── Runbook Agent      — searches Bedrock Knowledge Base for repo-specific runbooks
  ├── Communication Agent — posts Slack war room brief with users affected + blast radius
  └── (Orchestrator coordinates all five)
      ↓
Engineer pushes fix commit → marks incident resolved (with notes via dashboard modal)
      ↓
Fix Commit Detector — Nova verifies the diff actually reverses the bug (≥75% confidence)
      ↓
Postmortem Agent — generates full markdown postmortem with timeline, root cause,
                   verified fix commit hash, engineer notes, and action items
```

---

## What Makes It Real

Everything that matters is live data, not mocks:

| Feature | What It Actually Does |
|---|---|
| **User impact** | Scans README, k8s replicas, pool sizes, worker counts — anchors to explicit numbers if found |
| **Bug identification** | Fetches real unified diffs from GitHub API — Nova reads actual changed lines and cites specific line numbers |
| **Blast radius** | Parsed from real HTTP call patterns and env var references in the codebase |
| **Runbook matching** | Scraped from repo's own `docs/` folder at onboard time, uploaded to S3 + Bedrock KB |
| **Fix verification** | Nova reads the fix commit diff and confirms it reverses the original bug — not just "next commit = fix" |
| **Push filter** | Two-layer gate rejects safe commits (README edits, test changes) before any incident is created |

---

## Nova Usage

| Model | Where Used |
|---|---|
| **Nova Lite** | Push filter semantic risk check, triage severity classification, fix commit detection |
| **Nova Pro** | Deep investigation — reading unified diffs, identifying specific broken lines, root cause analysis |
| **Nova Multimodal Embeddings** | Bedrock Knowledge Base — semantic runbook search across repo-specific docs |

---

## Demo Scenario

The `ecommerce-platform` test repo is a realistic 4-microservice system with 124,000 daily active users (stated in README), 6 custom runbooks, and a real service dependency graph.

**One commit introduces two simultaneous failures:**
```python
# config/settings.py
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "0"))        # was 20 — connection exhaustion
TAX_RATE_MULTIPLIER = float(os.environ.get("TAX_RATE_MULTIPLIER", "0"))  # was 0.08 — regulatory violation
```

IncidentIQ fires in ~10 seconds:
- **HIGH severity** — Nova escalates because both infrastructure and compliance are affected
- **All 5 services** in blast radius
- **Both bugs identified** with exact line numbers — Line 25 and Line 66
- **3 repo-specific runbooks** matched — DB Pool Exhaustion, High Error Rate, Inventory Oversell
- **Slack war room** posted with full context

---

## Architecture

```
Frontend (React + Vite)          Backend (Python + FastAPI)
incidentiq-one.vercel.app   →    AWS ECS Fargate (incidentiq-cluster)
                                       ↓
                             ┌─────────────────────┐
                             │   DynamoDB Tables    │
                             │  incidentiq-repos    │
                             │  incidentiq-incidents│
                             └─────────────────────┘
                                       ↓
                             ┌─────────────────────┐
                             │   AWS Services       │
                             │  Bedrock (Nova)      │
                             │  Bedrock KB          │
                             │  S3 (runbooks)       │
                             │  Secrets Manager     │
                             └─────────────────────┘
                                       ↓
                             ┌─────────────────────┐
                             │   External           │
                             │  GitHub API          │
                             │  Slack Webhooks      │
                             └─────────────────────┘
```

---

## Running Locally

### Backend
```bash
cd backend
pip install -r requirements.txt

# Required environment variables
export AWS_REGION=us-east-1
export BEDROCK_KB_ID=your_kb_id
export BEDROCK_DATA_SOURCE_ID=your_datasource_id
export S3_BUCKET=your_bucket
export REPOS_TABLE=incidentiq-repos
export INCIDENTS_TABLE=incidentiq-incidents
export SLACK_CHANNEL=#incidents
export GITHUB_WEBHOOK_SECRET=your_secret

uvicorn api.main:app --reload --port 8000
```

### Frontend
```bash
cd dashboard
npm install
echo "VITE_API_BASE=http://localhost:8000" > .env.local
npm run dev
```

---

## Connecting a Repo

1. Open the dashboard
2. Click **+ Connect Repository**
3. Enter your GitHub repo (format: `owner/repo`) and a GitHub personal access token
4. IncidentIQ analyzes the repo — finds runbooks, builds service dependency graph, estimates DAU
5. A webhook is registered automatically — every push to `main` is now evaluated

---

## Deployment

### Backend (AWS ECS)
```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

# Build, tag, push
docker build -t incidentiq-backend .
docker tag incidentiq-backend:latest <account>.dkr.ecr.us-east-1.amazonaws.com/incidentiq-backend:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/incidentiq-backend:latest

# Deploy
aws ecs update-service --cluster incidentiq-cluster --service incidentiq-backend --force-new-deployment --region us-east-1
```

### Frontend (Vercel)
Set `VITE_API_BASE` environment variable to your backend URL and deploy via Vercel dashboard or CLI.

---

## Cost

IncidentIQ runs for pennies per incident. Nova Lite calls (push filter, triage) cost ~$0.001 each. Nova Pro calls (investigation) cost ~$0.01 each. A busy team pushing 50 times per day with 5 real incidents would spend under $1/day.

---

## Roadmap

- Multi-tenancy with org-scoped Bedrock KB namespaces
- GitHub token management via Secrets Manager per org
- Real DAU from CloudWatch/Datadog instead of estimated
- Webhook signature verification per environment
- PagerDuty integration for automated escalation
- Mobile push notifications for war room alerts



*IncidentIQ — The on-call engineer who never sleeps.*
