# 🧠 Serotonin Script

![Python](https://img.shields.io/badge/python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![Taskiq](https://img.shields.io/badge/Taskiq-0.11+-orange.svg)
![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen.svg)
![Lint](https://img.shields.io/badge/lint-Ruff%20%7C%20Pyright-purple.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

> AI-driven medical content engine using RAG (LlamaIndex + Qdrant), FastAPI, and Taskiq for automated multi-platform publishing with physician style preservation.

---

## 🎯 Overview

**Serotonin Script** is an autonomous system for generating and distributing medically-accurate content across social platforms. It leverages **RAG (Retrieval-Augmented Generation)** to ensure medical precision while preserving the unique authorial voice of healthcare professionals.

The system covers the full content lifecycle: from a single `/draft` Slack command → RAG-powered generation → physician approval → multi-platform publishing → post-publish vectorization for continuous style improvement.

### Key Capabilities
- **Style Preservation** — Vector-based retrieval of physician's writing patterns via hybrid search (dense + BM25)
- **Medical Accuracy** — Fact-checking against PubMed API and clinical guidelines (Chain-of-Verification)
- **Multi-Platform Publishing** — Automated distribution to Telegram, X (Twitter), Threads via n8n workflows
- **Async-First Architecture** — High-performance task processing via Taskiq + Redis (chosen over Celery: ~50-80 MB memory footprint vs ~150-200 MB, 1-2s startup vs 7-10s)
- **Slack-Native UX** — Draft approval workflow with interactive Block Kit UI
- **RAG Feedback Loop** — Published posts automatically vectorized back into Qdrant for continuous style learning
- **Production Observability** — Prometheus metrics, Grafana dashboards (backend, LLM costs, Taskiq queue), Loki log aggregation

---

## 🛠 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **API Framework** | FastAPI | Async-native REST API |
| **Task Queue** | [Taskiq](https://github.com/taskiq-python/taskiq) 0.11+ + Redis | Background job processing, async-native |
| **AI Engine** | Claude 3.5 Sonnet / GPT-4o | Content generation with LLM router + fallback |
| **Vector Store** | Qdrant | Semantic search for style matching and knowledge retrieval |
| **RAG Framework** | LlamaIndex | Retrieval-augmented generation pipeline |
| **Search** | Hybrid (dense + BM25) | Qdrant hybrid mode for improved retrieval precision |
| **External Data** | PubMed API + BeautifulSoup | Medical fact verification |
| **Orchestration** | n8n (self-hosted) | Workflow automation, scheduling, social delivery |
| **Database** | PostgreSQL + Alembic | Relational data with async sessions (asyncpg) |
| **Monitoring** | Prometheus + Grafana + Loki + Promtail | Metrics, dashboards, log aggregation |
| **Reverse Proxy** | Nginx | HTTPS termination |

### Why Taskiq over Celery?

| Aspect | Celery | Taskiq |
|--------|--------|--------|
| Architecture | Sync-first | Async-native (shared event loop with FastAPI) |
| Dependency Injection | Manual wiring | `TaskiqDepends` — identical to FastAPI |
| Memory per worker | ~150-200 MB | ~50-80 MB |
| Cold start | 7-10 seconds | 1-2 seconds |
| Type hints | Partial | Full (Pydantic-native) |
| Testing | Complex mocking | Direct `async` function calls |

See [ADR: Taskiq over Celery](docs/adr/003-taskiq-over-celery.md) for the full decision record.

---

## 📁 Project Structure

```text
serotonin_script/
├── backend/
│   ├── api/
│   │   ├── middleware/          # auth (Slack sig), error_handler, logging, rate_limit (Redis sliding-window)
│   │   └── routes/              # drafts, feedback (Slack interactions), health
│   ├── config/                  # settings (Pydantic), system_prompts, lexicon (Slack UI text)
│   ├── integrations/
│   │   ├── external/            # pubmed_client (NCBI E-utils), web_scraper (BeautifulSoup)
│   │   └── llm/                 # anthropic_client, openai_client, router (fallback logic)
│   ├── models/                  # db_models (SQLAlchemy 2.0), schemas (Pydantic v2), enums
│   ├── rag/
│   │   ├── indexing/            # document_loader (MD/PDF/TXT), chunking (SentenceSplitter), embedder
│   │   ├── pipelines/           # hybrid_search (dense + BM25)
│   │   └── retrieval/           # style_retriever, knowledge_retriever, base protocol
│   ├── repositories/            # draft_repository, feedback_repository, post_repository
│   ├── services/                # content_generator, draft_service, fact_checker, style_matcher, publisher_service
│   ├── utils/                   # structured logging (Structlog)
│   ├── workers/
│   │   ├── middlewares/         # LoggingMiddleware, RetryMiddleware (exp. backoff), PrometheusMiddleware
│   │   ├── tasks/               # generate_draft, publish_post, ingest_guideline, scheduled_post, vectorize_post
│   │   ├── broker.py            # Taskiq Redis broker (ListQueueBroker + RedisAsyncResultBackend, TTL 1h)
│   │   ├── callbacks.py         # Slack Block Kit notifications on task complete/failure
│   │   └── dependencies.py      # TaskiqDepends: StyleMatcher, FactChecker, LLMRouter, ContentGenerator, PublisherService
│   └── tests/
│       ├── unit/                # 20 test modules — services, RAG, workers, API, middleware
│       └── integration/         # test_draft_service.py (full service stack)
├── knowledge_base/
│   ├── doctor_style/            # Physician's articles & posts (.md) + metadata.json
│   └── medical_guidelines/      # Clinical protocol PDFs
├── slack_app/
│   ├── blocks/                  # draft_card.json, approval_modal.json, status_message.json
│   ├── handlers/                # slash_commands.py (/draft), interactions.py, events.py
│   └── utils/block_builder.py   # Dynamic Block Kit UI constructor
├── orchestration/
│   ├── n8n/                     # Workflow definitions + credentials guide
│   └── monitoring/              # n8n health check (circuit breaker)
├── database/
│   ├── migrations/              # Alembic versions (initial schema + platform/scheduled_at)
│   └── seeds/initial_data.sql
├── infra/
│   ├── docker/                  # Dockerfile.backend, Dockerfile.worker, Dockerfile.base
│   ├── monitoring/              # Prometheus, Grafana dashboards (backend/llm_costs/taskiq), Loki, Promtail
│   └── nginx/nginx.conf
├── scripts/
│   ├── index_knowledge_base.py  # Bulk ingestion into Qdrant
│   ├── test_pipeline.py         # E2E pipeline test
│   └── deploy.sh / migrate.sh / setup.sh
├── docs/
│   ├── architecture.md
│   ├── api_spec.yaml            # OpenAPI 3.0
│   ├── deployment.md
│   ├── runbook.md
│   ├── taskiq_guide.md
│   └── adr/                     # 001-vector-store, 002-llm-selection, 003-taskiq-over-celery
└── docker-compose.yml
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.13 (for local development)
- Slack workspace with `/draft` slash command configured
- API keys: Anthropic, OpenAI
- n8n credentials: Telegram Bot Token, X (Twitter) OAuth2, Threads Access Token (configured inside n8n, not in `.env`)

### Installation

```bash
# Clone repository
git clone https://github.com/PyDevDeep/serotonin-script.git
cd serotonin-script

# Configure environment
cp .env.example .env
# Edit .env with your API keys and credentials

# Start all services (API + worker + Redis + Qdrant + PostgreSQL + n8n + monitoring)
docker-compose up --build
```

### Service URLs

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| n8n Workflows | http://localhost:5678 |
| Grafana | http://localhost:3000 |

---

## 📖 Usage

### 1. Index Knowledge Base

```bash
# Ingest physician's writing samples + medical guidelines into Qdrant
python scripts/index_knowledge_base.py
```

Loads documents from `knowledge_base/doctor_style/` and `knowledge_base/medical_guidelines/` — chunks, embeds, and stores vectors in two separate Qdrant collections.

### 2. Generate Draft via Slack

```
/draft anxiety management tips
/draft depression coping strategies telegram
```

**Full workflow:**

```
Slack /draft
  └─► n8n Webhook
        └─► POST /api/v1/draft          ← returns task_id immediately (< 500ms)
              └─► Taskiq generate_draft task
                    ├── StyleMatcher   — retrieves top-5 physician posts (Qdrant)
                    ├── FactChecker    — PubMed API + web scraping + Chain-of-Verification
                    └── ContentGenerator (Claude 3.5 Sonnet → GPT-4o fallback)
                          └─► Slack callback → Block Kit draft card
```

### 3. Approve & Publish

From the Slack draft card:

- **Publish to Telegram / X / Threads** — triggers `publish_post` Taskiq task → `publisher_service.py` dispatches a webhook to n8n → n8n executes the platform-specific workflow (Telegram Bot API / Twitter API v2 / Threads API)
- **Edit** — opens Slack modal with full text editor + platform/schedule selector
- **Regenerate** — re-queues `generate_draft` with same topic

> **Publishing architecture note:** `publisher_service.py` is a thin dispatcher — it sends a structured webhook payload to n8n and tracks publication status in PostgreSQL. The actual social platform API calls (auth, formatting, retry logic) live entirely in n8n workflows under `orchestration/n8n/workflows/`. To modify platform-specific publishing behavior, edit the n8n workflow — not the Python service.

### 4. RAG Feedback Loop

After publishing, `vectorize_post` task automatically embeds the final approved text back into Qdrant (`doctor_style` collection) — the system continuously learns the physician's evolving style.

---

## 🔧 Development

### Run Tests

```bash
# Full test suite with coverage
make test

# Unit tests only
make test-unit

# Integration tests (requires running containers)
make test-integration
```

### Local Backend

```bash
# Install dependencies
poetry install

# Run API server
poetry run uvicorn backend.api.main:app --reload

# Run Taskiq worker (2 processes, max 10 concurrent async tasks)
poetry run taskiq worker backend.workers.broker:broker --workers 2 --max-async-tasks 10
```

### Database Migrations

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

---

## ✅ Test Coverage

**Overall: 97% (4394 statements, 148 missed)**

| Module | Coverage |
|--------|----------|
| `services/content_generator.py` | 100% |
| `services/draft_service.py` | 100% |
| `services/fact_checker.py` | 100% |
| `services/style_matcher.py` | 100% |
| `integrations/external/pubmed_client.py` | 100% |
| `integrations/llm/router.py` | 100% |
| `rag/pipelines/hybrid_search.py` | 100% |
| `rag/retrieval/knowledge_retriever.py` | 100% |
| `rag/retrieval/style_retriever.py` | 100% |
| `workers/tasks/generate_draft.py` | 100% |
| `workers/tasks/publish_post.py` | 100% |
| `workers/callbacks.py` | 100% |
| `api/middleware/error_handler.py` | 100% |
| `api/routes/feedback.py` | 96% |
| `services/publisher_service.py` | 91% |
| `workers/broker.py` | 80% |
| `api/middleware/auth.py` | 33% |
| `api/middleware/rate_limit.py` | 40% |

> Low coverage in `auth.py` (33%) and `rate_limit.py` (40%) reflects untested Slack signature verification edge cases and Redis sliding-window boundary conditions — these are integration-test candidates.

---

## 📊 Monitoring

Three pre-built Grafana dashboards:

| Dashboard | URL | Tracks |
|-----------|-----|--------|
| Backend Metrics | http://localhost:3000/d/backend_metrics | Request rate, latency (p95), error rate |
| LLM Costs | http://localhost:3000/d/llm_costs | Token usage, API calls, cost per platform |
| Taskiq Metrics | http://localhost:3000/d/taskiq_metrics | Queue depth, task duration, failure rate |

Prometheus alert rules configured for:
- Task failure rate > 5%/hour
- Queue depth > 100 tasks
- Task duration p95 > 60s
- LLM error rate > 10% in 5 minutes

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design and component interactions |
| [API Spec](docs/api_spec.yaml) | OpenAPI 3.0 specification |
| [Taskiq Guide](docs/taskiq_guide.md) | Async worker patterns and configuration |
| [Deployment](docs/deployment.md) | Production deployment guide |
| [Runbook](docs/runbook.md) | Operational procedures and troubleshooting |
| [ADR: Vector Store](docs/adr/001-vector-store-choice.md) | Qdrant selection rationale |
| [ADR: LLM Selection](docs/adr/002-llm-selection.md) | Claude + GPT-4o fallback design |
| [ADR: Taskiq vs Celery](docs/adr/003-taskiq-over-celery.md) | Task queue decision record |

---

## ⚙️ CI/CD

Three GitHub Actions workflows run on every push and pull request to `main`:

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `lint.yml` | push / PR → `main` | Ruff linter, Ruff formatter check, Pyright type checker |
| `test.yml` | push / PR → `main` | `poetry install` → `cp .env.example .env` → `pytest` |
| `build.yml` | `workflow_dispatch` only | Stub — Docker image build not yet automated |
| `deploy.yml` | `workflow_dispatch` only | Stub — automated deployment not yet implemented |

Linting and tests are blocking checks on PRs. Build and deploy pipelines are manual stubs pending a Docker registry and target server configuration.

---

## 🏭 Production Deployment

See [docs/deployment.md](docs/deployment.md) for the full guide. Quick reference:

### Docker Compose (VPS)

The production stack uses two Compose files layered together: `docker-compose.yml` (infrastructure services) and `infra/docker-compose.prod.yml` (application services).

```bash
# One-command deployment
bash scripts/deploy.sh
```

`deploy.sh` executes in order:
1. Tears down existing application containers (preserves named volumes)
2. Builds new images from `infra/docker/Dockerfile.base` (multi-stage, non-root user `seratonin`)
3. Starts `postgres` + `redis` and waits for health checks
4. Runs Alembic migrations via `scripts/migrate.sh`
5. Brings up all services

### Services in Production

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| `backend` | `Dockerfile.base` | `8001` | 2 Uvicorn workers, metrics disabled |
| `worker` | `Dockerfile.base` | `9000` | Taskiq worker, Prometheus metrics on `:9000` |
| `scheduler` | `Dockerfile.base` | `9001` | Taskiq scheduler for cron tasks |
| `postgres` | `postgres:15-alpine` | internal | External named volume `docker_postgres_data` |
| `redis` | `redis:7.2-alpine` | internal | AOF persistence, external volume `docker_redis_data` |
| `qdrant` | `qdrant/qdrant:latest` | internal | External volume `docker_qdrant_data` |
| `n8n` | `n8nio/n8n:latest` | `5678` | External volume `docker_n8n_data` |
| `prometheus` | `prom/prometheus` | `9090` | Scrapes backend `:8001/metrics` and worker `:9000` |
| `grafana` | `grafana/grafana` | `3000` | Dashboards: backend, LLM costs, Taskiq |
| `loki` + `promtail` | Grafana stack | `3100` | Log aggregation from Docker socket |

### Docker Image

`Dockerfile.base` uses a two-stage build:

```
Stage 1 (builder): python:3.13-slim
  └─ Poetry 2.0.1 exports requirements.txt (prod deps only)

Stage 2 (runtime): python:3.13-slim
  └─ Non-root user: seratonin:seratonin
  └─ Model cache dirs: /app/cache/huggingface, /app/cache/fastembed
  └─ Shared by: backend, worker, scheduler (different CMD per service)
```

### Persistent Volumes

All data volumes are declared as `external: true` with fixed names — they survive `docker-compose down` and must be pre-created on the host:

```bash
docker volume create docker_postgres_data
docker volume create docker_redis_data
docker volume create docker_qdrant_data
docker volume create docker_n8n_data
```

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for detailed guidelines.

---

## 📄 License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- **LlamaIndex** for the RAG framework
- **Taskiq** for modern async-native task processing
- **Qdrant** for vector search with hybrid mode

---

**Created by** [PyDevDeep](https://github.com/PyDevDeep)