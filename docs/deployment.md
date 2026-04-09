# 🏭 Deployment Guide

This document covers production deployment of Serotonin Script on a self-hosted VPS using Docker Compose.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- VPS with at least 4 GB RAM (8 GB recommended — model cache for FastEmbed/HuggingFace)
- Domain + TLS certificate (Nginx + Let's Encrypt)
- `.env` file populated from `.env.example`

---

## Repository Layout (Infra Files)

```text
├── docker-compose.yml              # Root compose: includes infra services + dev overrides + monitoring
├── infra/
│   ├── docker/
│   │   ├── docker-compose.yml      # Infrastructure services: postgres, redis, qdrant, n8n
│   │   ├── docker-compose.dev.yml  # Dev overrides: exposes DB/Redis/Qdrant ports
│   │   ├── docker-compose.prod.yml # App services: backend, worker, scheduler
│   │   ├── Dockerfile.base         # Multi-stage image (builder → runtime, non-root user)
│   │   └── Dockerfile.backend      # (reserved, currently empty)
│   ├── monitoring/
│   │   ├── prometheus/prometheus.yml
│   │   ├── grafana/dashboards/     # backend_metrics.json, llm_costs.json, taskiq_metrics.json
│   │   ├── loki/loki-config.yaml
│   │   └── promtail-config.yml
│   └── nginx/nginx.conf
└── scripts/
    ├── deploy.sh                   # One-command production deploy
    ├── migrate.sh                  # Alembic migration runner
    └── setup.sh                    # First-time host setup
```

---

## Compose File Architecture

The stack is built from layered Compose files:

### Development (default `docker-compose.yml`)

```yaml
include:
  - infra/docker/docker-compose.yml     # postgres, redis, qdrant, n8n
  - infra/docker-compose.dev.yml        # exposes external ports (configurable via .env)

services:
  prometheus, grafana, loki, promtail   # monitoring stack
```

Dev overrides expose ports for direct database access:

| Service | Default External Port | Env Variable |
|---------|-----------------------|-------------|
| PostgreSQL | `5433` | `EXTERNAL_POSTGRES_PORT` |
| Redis | `6380` | `EXTERNAL_REDIS_PORT` |
| Qdrant | `6333` / `6334` (gRPC) | `EXTERNAL_QDRANT_PORT` / `EXTERNAL_QDRANT_GRPC_PORT` |
| n8n | `5678` | — |

### Production

```bash
docker-compose.yml + infra/docker-compose.prod.yml
```

`docker-compose.prod.yml` adds three application services on top of infrastructure:

| Service | Command | Port | ENV specifics |
|---------|---------|------|---------------|
| `backend` | `uvicorn ... --workers 2` | `8001` | `START_METRICS=false` |
| `worker` | `taskiq worker backend.workers.broker:broker backend.workers.tasks` | `9000` | `START_METRICS=true`, model cache volume |
| `scheduler` | `taskiq scheduler backend.workers.broker:scheduler backend.workers.tasks` | `9001` | `START_METRICS=true` |

All three services build from the same `Dockerfile.base`. The `CMD` is provided per-service in the Compose file.

---

## Docker Image

`infra/docker/Dockerfile.base` — shared base for `backend`, `worker`, and `scheduler`:

```dockerfile
# Stage 1: builder
FROM python:3.13-slim AS builder
# Exports production-only requirements.txt via Poetry (excludes dev deps)

# Stage 2: runtime
FROM python:3.13-slim
# Non-root user: seratonin:seratonin
# Model cache dirs: /app/cache/huggingface, /app/cache/fastembed
# Mounts as named volume in worker/scheduler services
```

The non-root user (`seratonin`) owns the entire `/app` directory. The model cache is mounted as a named Docker volume (`model_cache`) so HuggingFace and FastEmbed models persist across container restarts and are not re-downloaded.

---

## Persistent Volumes

All data volumes are declared `external: true`. They must be created on the host before the first deploy:

```bash
docker volume create docker_postgres_data
docker volume create docker_redis_data
docker volume create docker_qdrant_data
docker volume create docker_n8n_data
```

These volumes survive `docker-compose down` and `docker-compose down --remove-orphans`. They are **not** removed unless you explicitly run `docker volume rm`.

---

## Environment Configuration

```bash
cp .env.example .env
```

Required variables:

```dotenv
# Database
POSTGRES_USER=seratonin
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=seratonin_db

# Redis
REDIS_HOST=redis

# Qdrant
QDRANT_HOST=qdrant

# LLM APIs
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...

# Grafana
GRAFANA_PASSWORD=<strong-password>

# n8n
# Telegram, X (Twitter), Threads credentials are configured
# directly inside n8n UI → Credentials, not via .env
```

---

## First-Time Setup

```bash
# 1. Create external volumes
docker volume create docker_postgres_data
docker volume create docker_redis_data
docker volume create docker_qdrant_data
docker volume create docker_n8n_data

# 2. Configure environment
cp .env.example .env
# Edit .env

# 3. Run setup script (installs system deps, validates env)
bash scripts/setup.sh

# 4. Deploy
bash scripts/deploy.sh
```

---

## Production Deploy (Subsequent Runs)

```bash
bash scripts/deploy.sh
```

`deploy.sh` executes the following steps in order:

```bash
# Step 1: Tear down existing app containers (preserves volumes)
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml down --remove-orphans

# Step 2: Build new images
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d --build

# Step 3: Start database services and wait for health checks
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d postgres redis

# Step 4: Run Alembic migrations
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend bash scripts/migrate.sh

# Step 5: Bring up all services
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d
```

Health checks are defined on `postgres` (pg_isready) and `redis` (redis-cli ping) — the `backend` and `worker` services declare `depends_on: condition: service_healthy` and will not start until both pass.

---

## Service URLs (Production)

| Service | URL | Notes |
|---------|-----|-------|
| API | `http://localhost:8001` | Behind Nginx in production |
| API Docs | `http://localhost:8001/docs` | Swagger UI |
| n8n | `http://localhost:5678` | Configure publishing workflows here |
| Prometheus | `http://localhost:9090` | |
| Grafana | `http://localhost:3000` | Default password: `GRAFANA_PASSWORD` from `.env` |
| Loki | `http://localhost:3100` | Accessed via Grafana datasource |
| Worker metrics | `http://localhost:9000/metrics` | Taskiq Prometheus metrics |
| Scheduler metrics | `http://localhost:9001/metrics` | Taskiq scheduler metrics |

---

## n8n Publishing Workflows

Social platform credentials (Telegram, X/Twitter, Threads) are **not** in `.env` — they are stored in n8n's encrypted credential store.

After first deploy:

1. Open `http://localhost:5678`
2. Go to **Credentials** → create credentials for each platform
3. Import workflow definitions from `orchestration/n8n/workflows/`
4. Activate workflows
5. Verify webhook URLs match the `WEBHOOK_URL` env variable

See `orchestration/n8n/credentials/README.md` for the full credential setup guide.

---

## CI/CD Status

| Workflow | Status | Trigger |
|----------|--------|---------|
| Lint (Ruff + Pyright) | ✅ Active | Push / PR → `main` |
| Tests (pytest) | ✅ Active | Push / PR → `main` |
| Build (Docker image) | 🚧 Stub | `workflow_dispatch` only |
| Deploy (automated) | 🚧 Stub | `workflow_dispatch` only |

Automated build and deploy pipelines are pending Docker registry configuration and target server SSH setup. Until then, deploy manually via `scripts/deploy.sh`.

---

## Monitoring Verification

After deployment, verify all three Grafana dashboards are receiving data:

```
http://localhost:3000/d/backend_metrics  — FastAPI request rate, latency (p95), error rate
http://localhost:3000/d/llm_costs        — Token usage, API calls, cost per platform
http://localhost:3000/d/taskiq_metrics   — Queue depth, task duration, failure rate
```

Prometheus scrape targets:

```yaml
# infra/monitoring/prometheus/prometheus.yml
- backend:8001/metrics     # FastAPI (prometheus-fastapi-instrumentator)
- worker:9000/metrics      # Taskiq worker (PrometheusMiddleware)
- scheduler:9001/metrics   # Taskiq scheduler
- redis_exporter:9121      # Redis metrics
- postgres_exporter:9187   # PostgreSQL metrics
```

---

## Troubleshooting

**Containers not starting after deploy:**
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml logs backend
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml logs worker
```

**Migrations fail:**
```bash
# Run migrations manually with output
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic upgrade head
```

**Worker not processing tasks:**
```bash
# Check Redis connectivity from worker
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec worker redis-cli -h redis ping
```

**Model cache missing (FastEmbed re-downloading on every restart):**
Verify the `model_cache` named volume is mounted correctly in `docker-compose.prod.yml`:
```yaml
volumes:
  - model_cache:/app/cache
```

See [runbook.md](runbook.md) for operational procedures and alert response playbooks.