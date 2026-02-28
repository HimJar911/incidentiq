# ── IncidentIQ Backend — Production Dockerfile ────────────────────────────────
# Multi-stage build: keeps final image lean by not including build tools.
#
# Build context: project root (IncidentIQ/)
# Run: uvicorn backend.api.main:app on port 8000
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies into a target directory
COPY backend/requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
# We copy the entire backend/ package so all imports work as-is
COPY backend/ ./backend/

# Copy replay payloads (used by /api/replay endpoint)
COPY replay/ ./replay/

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Port the FastAPI app listens on
EXPOSE 8000

# Health check — used by ECS to determine if task is healthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Start uvicorn
# - host 0.0.0.0 so ALB can reach it
# - workers 2 for light concurrency (Fargate 0.25 vCPU)
# - timeout-keep-alive 65 matches ALB idle timeout
CMD ["uvicorn", "backend.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--timeout-keep-alive", "65", \
     "--log-level", "info"]