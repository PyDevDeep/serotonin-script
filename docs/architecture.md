# Architecture: Serotonin Script

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Component Diagram](#2-high-level-component-diagram)
3. [Request Lifecycle](#3-request-lifecycle)
4. [Layer-by-Layer Breakdown](#4-layer-by-layer-breakdown)
   - [4.1 API Layer](#41-api-layer)
   - [4.2 Service Layer](#42-service-layer)
   - [4.3 RAG Pipeline](#43-rag-pipeline)
   - [4.4 Async Workers (Taskiq)](#44-async-workers-taskiq)
   - [4.5 Publishing Architecture](#45-publishing-architecture)
   - [4.6 Slack Integration](#46-slack-integration)
5. [Data Model](#5-data-model)
6. [Infrastructure](#6-infrastructure)
7. [Observability](#7-observability)
8. [Architecture Decision Records](#8-architecture-decision-records)

---

## 1. System Overview

Serotonin Script is an autonomous content pipeline designed for a single physician. It takes a topic from a Slack command and produces a medically-accurate post in that physician's writing style, ready to approve and publish to social platforms.

The system has three distinct responsibilities:

- **Generation** — RAG-powered draft creation with style matching and fact-checking
- **Approval** — Slack-native review and editing workflow
- **Distribution** — n8n-orchestrated publishing to Telegram, X (Twitter), and Threads

These map cleanly to three process types: the FastAPI application (synchronous HTTP), Taskiq workers (async background tasks), and n8n workflows (event-driven automation).

---

## 2. High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          PHYSICIAN                                   │
│                    types: /draft [topic]                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ Slack slash command
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  SLACK                       │  n8n (self-hosted)                    │
│  Block Kit UI                │  ┌─────────────────────────────────┐  │
│  • /draft command            │  │ Webhook Trigger                 │  │
│  • Draft card                │  │ POST /api/v1/draft              │  │
│  • Approve / Edit /          │  │ Poll task status                │  │
│    Regenerate buttons        │  │ Platform publish workflows      │  │
│  • Approval modal            │  └─────────────────────────────────┘  │
└──────────────────────────────┴──────────────────┬───────────────────┘
                                                  │ HTTP
                                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FASTAPI APPLICATION  (backend:8001)                                 │
│                                                                      │
│  Middleware stack:                                                   │
│  auth.py → rate_limit.py → logging.py → error_handler.py            │
│                                                                      │
│  Routes:                                                             │
│  POST /api/v1/draft          → enqueues generate_draft task          │
│  GET  /api/v1/draft/{id}     → polls Taskiq result backend           │
│  POST /slack/commands        → /draft slash command handler          │
│  POST /slack/interactions    → button/modal callbacks                │
│  GET  /health                → liveness + readiness probes           │
│  GET  /metrics               → Prometheus scrape endpoint            │
└────────────────────────────┬────────────────────────────────────────┘
                             │ task.kiq() — async dispatch
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  REDIS                                                               │
│  • Task queue:   seratonin_tasks (ListQueueBroker)                   │
│  • Result store: RedisAsyncResultBackend (TTL 1h)                    │
│  • Rate limiter: sliding-window counters                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ task consumption
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TASKIQ WORKERS  (worker:9000)                                       │
│                                                                      │
│  Middlewares: LoggingMiddleware → RetryMiddleware → PrometheusMiddleware │
│                                                                      │
│  Tasks:                                                              │
│  generate_draft    — full RAG + LLM generation pipeline              │
│  publish_post      — dispatches webhook to n8n                       │
│  vectorize_post    — embeds published post back into Qdrant          │
│  ingest_guideline  — indexes new medical guidelines                  │
│  scheduled_post    — checks and triggers scheduled publications      │
│                                                                      │
│  TASKIQ SCHEDULER  (scheduler:9001)                                  │
│  Cron trigger for scheduled_post task                                │
└──────┬──────────────────────────────────────────────────────────────┘
       │
       ├─────────────────────────────────────────────┐
       │                                             │
       ▼                                             ▼
┌──────────────────────────┐         ┌───────────────────────────────┐
│  QDRANT                  │         │  POSTGRESQL                   │
│  Collections:            │         │  Tables:                      │
│  • doctor_style          │         │  • drafts                     │
│    (writing patterns)    │         │  • posts                      │
│  • medical_knowledge     │         │  • feedback                   │
│    (clinical guidelines) │         │                               │
│  Hybrid search:          │         │  Managed via:                 │
│  dense (embeddings)      │         │  SQLAlchemy 2.0 async         │
│  + sparse (BM25)         │         │  + Alembic migrations         │
└──────────────────────────┘         └───────────────────────────────┘
       │
       ├── LLM ROUTER ──────────────────────────────────────────────┐
                                                                     │
                                    ┌────────────────────────────────┤
                                    │  Claude 3.5 Sonnet (primary)   │
                                    │  GPT-4o (fallback)             │
                                    └────────────────────────────────┘
```

---

## 3. Request Lifecycle

### 3.1 Draft Generation (`/draft [topic]`)

```
1. Physician types: /draft anxiety management tips

2. Slack → n8n webhook (POST /webhook/draft)
   └─ n8n calls: POST /api/v1/draft {topic, platform, channel_id}

3. FastAPI:
   ├─ Middleware: verify Slack signature (auth.py)
   ├─ Middleware: check rate limit — 10 req/min per user (rate_limit.py)
   └─ Route: enqueue generate_draft.kiq(topic, platform, channel_id)
      └─ Returns: {task_id} immediately — response < 500ms

4. Taskiq worker picks up generate_draft:
   a. StyleMatcher.get_context(topic)
      └─ Qdrant hybrid search → top-5 physician posts
   b. FactChecker.verify(topic)
      ├─ PubMed API (NCBI E-utilities) — fetch relevant abstracts
      ├─ BeautifulSoup web scraper — fetch supporting web sources
      └─ Chain-of-Verification — cross-check claims against sources
   c. ContentGenerator.generate(topic, style_context, fact_context)
      ├─ LLMRouter selects: Claude 3.5 Sonnet (primary)
      │                   → GPT-4o if Anthropic unavailable (fallback)
      └─ Returns: DraftResult(content, sources, platform)

5. Taskiq callback (callbacks.py):
   └─ Slack Web API → send Block Kit draft_card to channel_id
      Card contains: draft text, fact-check sources,
                     [Publish] [Edit] [Regenerate] buttons
```

### 3.2 Approval & Publishing

```
6. Physician clicks [Publish to Telegram]

7. Slack interaction → POST /slack/interactions
   └─ FastAPI → enqueue publish_post.kiq(draft_id, platform="telegram")

8. Taskiq worker picks up publish_post:
   └─ PublisherService.publish(content, platform)
      └─ POST n8n webhook /webhook/publish/telegram
         └─ n8n Telegram workflow:
            ├─ Telegram Bot API → send to channel
            └─ POST /api/v1/draft/{id}/status {status: PUBLISHED}

9. Taskiq worker picks up vectorize_post (triggered after publish):
   └─ Embeds published text → Qdrant doctor_style collection
      (RAG feedback loop — continuous style improvement)

10. Slack notification: "✅ Published to Telegram"
```

### 3.3 Scheduled Publishing

```
Taskiq Scheduler (cron) → scheduled_post task
  └─ Query PostgreSQL: drafts WHERE scheduled_at <= NOW() AND status = PENDING
     └─ For each: enqueue publish_post.kiq(draft_id, platform)
```

---

## 4. Layer-by-Layer Breakdown

### 4.1 API Layer

**Location:** `backend/api/`

#### Middleware Stack (applied in order)

| Middleware | File | Responsibility |
|-----------|------|----------------|
| Auth | `middleware/auth.py` | Slack request signature verification (HMAC-SHA256) |
| Rate Limit | `middleware/rate_limit.py` | Redis sliding-window: 10 req/min per user on `/draft`, 5 req/min on publish endpoints |
| Logging | `middleware/logging.py` | Structured request/response logging via Structlog |
| Error Handler | `middleware/error_handler.py` | Catches domain exceptions → HTTP responses with consistent error schema |

#### Routes

| Route | Method | Handler | Notes |
|-------|--------|---------|-------|
| `/api/v1/draft` | POST | `drafts.py` | Enqueues `generate_draft`, returns `task_id` |
| `/api/v1/draft/{task_id}` | GET | `drafts.py` | Polls Redis result backend |
| `/slack/commands` | POST | `feedback.py` | `/draft` slash command entry point |
| `/slack/interactions` | POST | `feedback.py` | Button clicks, modal submissions |
| `/health` | GET | `health.py` | Liveness + readiness probes |
| `/metrics` | GET | auto (instrumentator) | Prometheus scrape |

#### Dependency Injection

`dependencies.py` wires database sessions and repository instances via `FastAPI.Depends`. Each request gets an isolated async DB session; repositories are stateless and receive the session as an argument.

---

### 4.2 Service Layer

**Location:** `backend/services/`

The service layer contains all business logic. Services are pure Python classes with no HTTP or database concerns — they receive dependencies via constructor injection (FastAPI) or `TaskiqDepends` (workers).

#### ContentGenerator

Orchestrates the full generation pipeline:

```
ContentGenerator.generate(topic, platform)
  ├─ StyleMatcher.get_context(topic)        → style_context: list[str]
  ├─ FactChecker.verify(topic)              → fact_context: VerificationResult
  └─ LLMRouter.complete(prompt)             → DraftResult
```

#### StyleMatcher

Queries the `doctor_style` Qdrant collection with hybrid search, returns the top-5 most semantically similar physician posts as style context for the prompt.

#### FactChecker

Three-stage medical fact verification:

1. **PubMed** — queries NCBI E-utilities API for relevant abstracts
2. **Web scraping** — fetches top web sources via BeautifulSoup
3. **Chain-of-Verification** — LLM pass that cross-checks the proposed content against the retrieved sources, flags unverified claims

#### LLMRouter

Selects the active LLM based on availability. Primary: Claude 3.5 Sonnet via Anthropic SDK. Fallback: GPT-4o via OpenAI SDK. The router catches API errors from the primary and transparently retries via the fallback without surfacing the switch to callers.

#### DraftService

Manages draft lifecycle: creation, status tracking, retrieval. Coordinates between the API layer and repositories.

#### PublisherService

A thin dispatcher. Accepts `(content, platform)`, formats a webhook payload, and POSTs to the corresponding n8n webhook URL. Does not contain any platform-specific API logic — that lives entirely in n8n workflows. Updates draft status in PostgreSQL after dispatching.

---

### 4.3 RAG Pipeline

**Location:** `backend/rag/`

#### Indexing

Documents enter the system via `scripts/index_knowledge_base.py`, which drives the indexing pipeline:

```
File (MD / PDF / TXT)
  └─ DocumentLoader        — reads file, normalizes to LlamaIndex Document objects
       └─ SentenceSplitter — chunks at sentence boundaries
            (chunk_size=512, overlap=50)
              └─ Embedder  — generates dense vectors (FastEmbed)
                   └─ Qdrant — stores vectors in named collection
```

Two collections in Qdrant:

| Collection | Source | Used by |
|-----------|--------|---------|
| `doctor_style` | `knowledge_base/doctor_style/` — physician's articles and posts | StyleMatcher, vectorize_post (feedback loop) |
| `medical_knowledge` | `knowledge_base/medical_guidelines/` — clinical protocol PDFs | KnowledgeRetriever (FactChecker) |

#### Retrieval

Both retrievers share a common base protocol (`retrieval/base.py`) and are configured independently:

- **StyleRetriever** — queries `doctor_style`, returns top-5 results, optimized for stylistic similarity
- **KnowledgeRetriever** — queries `medical_knowledge`, returns top-3 results, optimized for factual precision

#### Hybrid Search

`pipelines/hybrid_search.py` combines dense vector similarity (cosine) with BM25 sparse retrieval using Qdrant's hybrid mode. This improves recall for medical terminology, which may not be well-represented in embedding space alone.

---

### 4.4 Async Workers (Taskiq)

**Location:** `backend/workers/`

#### Why Taskiq

Taskiq runs in the same async event loop as FastAPI. Worker tasks are ordinary `async def` functions decorated with `@broker.task` — no separate process model, no sync/async boundary friction. See [ADR: Taskiq over Celery](adr/003-taskiq-over-celery.md).

#### Broker Configuration

```python
# broker.py
broker = ListQueueBroker(redis_url)
    .with_result_backend(RedisAsyncResultBackend(redis_url, result_ex_time=3600))
    .with_middlewares(LoggingMiddleware(), RetryMiddleware(), PrometheusMiddleware())
```

Queue name: `seratonin_tasks`. Result TTL: 1 hour.

#### Middleware Pipeline

Every task execution passes through three middlewares in order:

| Middleware | File | Behavior |
|-----------|------|---------|
| LoggingMiddleware | `middlewares/logging.py` | Structured logs: task name, args, duration, outcome |
| RetryMiddleware | `middlewares/retry.py` | Exponential backoff, max 3 retries, base delay 5s |
| PrometheusMiddleware | `middlewares/metrics.py` | Increments counters and histograms on worker port `:9000` |

#### Task Registry

| Task | Timeout | Priority | Triggered by |
|------|---------|----------|-------------|
| `generate_draft` | 60s | high | API `POST /draft` |
| `publish_post` | 30s | medium | Slack interaction (Approve button) |
| `vectorize_post` | 30s | low | After successful publish |
| `ingest_guideline` | 120s | low | Manual / admin |
| `scheduled_post` | 30s | medium | Taskiq Scheduler (cron) |

#### Dependency Injection in Workers

`dependencies.py` uses `TaskiqDepends` — syntactically identical to `FastAPI.Depends`. Each task declares its service dependencies as function arguments:

```python
@broker.task(timeout=60, label="priority:high")
async def generate_draft(
    topic: str,
    platform: str,
    generator: ContentGenerator = TaskiqDepends(get_content_generator),
    repo: DraftRepository = TaskiqDepends(get_draft_repository),
) -> DraftResult:
    ...
```

This makes tasks directly testable as plain async functions by passing mock dependencies.

---

### 4.5 Publishing Architecture

Publishing in Serotonin Script follows a deliberate two-layer split:

```
Python (publisher_service.py)          n8n (workflows)
─────────────────────────────          ────────────────────────────
• Receives publish intent              • Owns platform credentials
• Formats webhook payload              • Handles platform-specific API
• POSTs to n8n webhook URL               formatting and auth
• Updates draft status in DB           • Manages retry on platform errors
• Sends Slack success/fail callback    • Updates DB status via callback
```

This split means: adding a new platform requires only a new n8n workflow, with no Python changes. Platform credentials (Telegram Bot Token, Twitter OAuth2, Threads Access Token) are stored exclusively in n8n's encrypted credential store — they never appear in `.env` or Python code.

**n8n workflow locations:** `orchestration/n8n/workflows/`

| Workflow | Trigger | Platform API |
|---------|---------|-------------|
| `main_draft_flow.json` | Slack /draft → webhook | Routes to appropriate publish workflow |
| `telegram_publish.json` | `/webhook/publish/telegram` | Telegram Bot API |
| `twitter_publish.json` | `/webhook/publish/twitter` | Twitter API v2 (thread splitting) |
| `threads_publish.json` | `/webhook/publish/threads` | Threads API |
| `scheduled_post.json` | Wait node (scheduled_at) | Delegates to platform workflows |

---

### 4.6 Slack Integration

**Location:** `slack_app/`

Slack is the sole human interface — the physician never interacts with n8n or the API directly.

#### Entry Points

| Event | Handler | FastAPI route |
|-------|---------|--------------|
| `/draft [topic]` | `handlers/slash_commands.py` | `POST /slack/commands` |
| Button click (Approve / Regenerate) | `handlers/interactions.py` | `POST /slack/interactions` |
| Modal submit (Edit + save) | `handlers/interactions.py` | `POST /slack/interactions` |
| App home opened | `handlers/events.py` | via Events API |

#### Block Kit UI

`utils/block_builder.py` constructs dynamic Block Kit payloads at runtime:

- `build_draft_card(draft)` — displays generated text, fact-check sources, action buttons
- `build_approval_modal(draft)` — text editor, platform selector, optional schedule picker
- `build_status_message(status)` — publish confirmation or error notification

Block Kit JSON templates: `blocks/draft_card.json`, `blocks/approval_modal.json`, `blocks/status_message.json`

---

## 5. Data Model

### PostgreSQL Tables

#### `drafts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `topic` | VARCHAR | User-supplied generation topic |
| `content` | TEXT | Generated draft text |
| `platform` | ENUM | `telegram`, `twitter`, `threads` |
| `status` | ENUM | `pending`, `approved`, `published`, `failed` |
| `scheduled_at` | TIMESTAMP | NULL = immediate publish |
| `task_id` | VARCHAR | Taskiq task ID for status polling |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

#### `posts`

Immutable record of what was actually published: final content, platform, published timestamp, external post ID returned by the platform.

#### `feedback`

Stores Slack interaction events: which button was clicked, by whom, on which draft. Used for monitoring physician engagement patterns.

### Qdrant Collections

| Collection | Vector dim | Distance | Payload fields |
|-----------|-----------|----------|---------------|
| `doctor_style` | 384 | Cosine | `text`, `source`, `date`, `platform`, `topic` |
| `medical_knowledge` | 384 | Cosine | `text`, `source`, `guideline_name`, `section` |

Both collections use FastEmbed (`BAAI/bge-small-en-v1.5`) for embedding generation. BM25 sparse vectors are computed by Qdrant at index time.

---

## 6. Infrastructure

### Docker Services

The production stack is assembled from two Compose files:

```
docker-compose.yml                     — dev (includes infra + monitoring)
infra/docker/docker-compose.yml        — infrastructure services
infra/docker-compose.prod.yml          — application services (backend, worker, scheduler)
```

All data volumes are external named volumes, pre-created on the host, and survive container teardown.

### Network Topology

All services communicate over the internal Docker network. Only the following ports are exposed externally in production:

| Port | Service | Access |
|------|---------|--------|
| `8001` | backend (via Nginx) | Public (HTTPS via Nginx) |
| `5678` | n8n | Internal / VPN |
| `3000` | Grafana | Internal / VPN |
| `9090` | Prometheus | Internal |

### Non-Root Container User

All application containers (`backend`, `worker`, `scheduler`) run as the `seratonin` user (UID not root). The user and group are created in `Dockerfile.base` and own the entire `/app` directory.

---

## 7. Observability

### Metrics (Prometheus)

Three scrape targets provide full-stack coverage:

| Target | Port | What it exports |
|--------|------|----------------|
| `backend` | `8001/metrics` | HTTP request rate, latency histogram (p50/p95/p99), error rate — via `prometheus-fastapi-instrumentator` |
| `worker` | `9000/metrics` | Task execution counter (by task name and status), task duration histogram — via `PrometheusMiddleware` |
| `scheduler` | `9001/metrics` | Scheduled task trigger count |

### Grafana Dashboards

| Dashboard | File | Key panels |
|-----------|------|-----------|
| Backend Metrics | `grafana/dashboards/backend_metrics.json` | Request rate, p95 latency, 5xx error rate, active connections |
| LLM Costs | `grafana/dashboards/llm_costs.json` | Token usage per model, cost per platform, Anthropic vs OpenAI split |
| Taskiq Metrics | `grafana/dashboards/taskiq_metrics.json` | Queue depth, task duration p95, failure rate, retry count |

### Alerts

Alert rules fire to Grafana Alerting (or Alertmanager if configured):

| Alert | Condition | Severity |
|-------|-----------|---------|
| High task failure rate | `taskiq_task_failures_total` > 5% over 1h | warning |
| Queue backlog | queue depth > 100 tasks | warning |
| Slow generation | task duration p95 > 60s | warning |
| LLM errors | LLM request error rate > 10% over 5min | critical |

### Logging (Loki)

Promtail collects logs from the Docker socket and forwards to Loki. All application logs are structured JSON (Structlog), with fields: `timestamp`, `level`, `service`, `task_id` (where applicable), `user_id`, `event`.

Logs are queryable via Grafana's Explore interface using LogQL.

---

## 8. Architecture Decision Records

Full rationale for key design decisions:

| ADR | Decision | Summary |
|-----|---------|---------|
| [001](adr/001-vector-store-choice.md) | Qdrant over Pinecone / Weaviate | Self-hosted, hybrid search native, no managed service dependency |
| [002](adr/002-llm-selection.md) | Claude 3.5 Sonnet primary, GPT-4o fallback | Medical writing quality + cost; fallback ensures availability |
| [003](adr/003-taskiq-over-celery.md) | Taskiq over Celery | Async-native, shared event loop, lower memory, native DI |