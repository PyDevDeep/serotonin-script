# Runbook: Serotonin Script

Operational reference for on-call response, troubleshooting, and routine maintenance.

## Table of Contents

1. [Service Map & Health URLs](#1-service-map--health-urls)
2. [Alert Response Playbooks](#2-alert-response-playbooks)
   - [High Task Failure Rate](#21-high-task-failure-rate)
   - [Queue Backlog](#22-queue-backlog)
   - [Slow Generation (p95 > 60s)](#23-slow-generation-p95--60s)
   - [LLM Error Rate Critical](#24-llm-error-rate-critical)
3. [Common Failure Scenarios](#3-common-failure-scenarios)
   - [/draft command returns no response in Slack](#31-draft-command-returns-no-response-in-slack)
   - [Draft generated but Publish button does nothing](#32-draft-generated-but-publish-button-does-nothing)
   - [Worker container keeps restarting](#33-worker-container-keeps-restarting)
   - [Migrations fail on deploy](#34-migrations-fail-on-deploy)
   - [Qdrant collection missing / RAG returning empty results](#35-qdrant-collection-missing--rag-returning-empty-results)
4. [Diagnostic Commands](#4-diagnostic-commands)
5. [Routine Maintenance](#5-routine-maintenance)
6. [Emergency Procedures](#6-emergency-procedures)

---

## 1. Service Map & Health URLs

| Service | Internal host | Health check | Exposed port |
|---------|--------------|-------------|-------------|
| FastAPI backend | `backend:8001` | `GET /health` | 8001 (via Nginx) |
| Taskiq worker | `worker:9000` | Redis ping (healthcheck in compose) | 9000 (metrics only) |
| Taskiq scheduler | `scheduler:9001` | Redis ping | 9001 (metrics only) |
| PostgreSQL | `postgres:5432` | `pg_isready` | internal |
| Redis | `redis:6379` | `redis-cli ping` | internal |
| Qdrant | `qdrant:6333` | `GET /healthz` | internal |
| n8n | `n8n:5678` | `GET /healthz` | 5678 |
| Prometheus | `prometheus:9090` | `GET /-/healthy` | 9090 |
| Grafana | `grafana:3000` | `GET /api/health` | 3000 |
| Loki | `loki:3100` | `GET /ready` | 3100 |

**Quick health check across all services:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml ps
```

All services should show status `Up` with `(healthy)` on those that define a healthcheck.

---

## 2. Alert Response Playbooks

### 2.1 High Task Failure Rate

**Alert:** `taskiq_task_failures_total` > 5% over 1 hour

**Grafana:** `http://localhost:3000/d/taskiq_metrics` → "Task failure rate" panel

**Step 1 — Identify which task is failing:**

```bash
# View worker logs, filter for ERROR level
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 1h | grep '"level":"error"'
```

Look for `task_name` field in the JSON log output.

**Step 2 — Check if it's an LLM error:**

```bash
# Look for Anthropic / OpenAI API errors
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 1h | grep -i "anthropic\|openai\|llm"
```

If LLM errors — see [2.4 LLM Error Rate Critical](#24-llm-error-rate-critical).

**Step 3 — Check if it's a database error:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec postgres pg_isready -U seratonin -d seratonin_db
```

**Step 4 — Check retry exhaustion:**

If logs show `max_retries=3 exhausted`, the task has been attempted 3 times with exponential backoff (5s, 10s, 20s) and failed all three. This indicates a persistent external dependency issue, not a transient error.

**Resolution:** Fix the underlying dependency (LLM API, database, Qdrant), then re-enqueue failed drafts manually if needed.

---

### 2.2 Queue Backlog

**Alert:** Taskiq queue depth > 100 tasks

**Grafana:** `http://localhost:3000/d/taskiq_metrics` → "Queue depth" panel

**Step 1 — Check queue depth directly:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec redis redis-cli LLEN seratonin_tasks
```

**Step 2 — Check if workers are running:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml ps worker
```

If worker is down: `docker compose ... up -d worker`

**Step 3 — Check if workers are processing (not stuck):**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 5m | grep "task_started\|task_completed"
```

If no `task_completed` entries are appearing, workers may be deadlocked on a slow external call (LLM, PubMed). Check task timeouts.

**Step 4 — Scale workers temporarily if backlog is legitimate:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  up -d --scale worker=3
```

Note: scaling workers increases LLM API concurrency — monitor token rate limits.

---

### 2.3 Slow Generation (p95 > 60s)

**Alert:** Task duration p95 > 60s for `generate_draft`

**Grafana:** `http://localhost:3000/d/taskiq_metrics` → "Task duration p95" panel

The `generate_draft` task has a 60s timeout. p95 approaching this threshold means some requests are failing due to timeout before the alert fires.

**Step 1 — Identify the slow stage:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 1h | grep "generate_draft" | grep -E "style_match|fact_check|llm_complete"
```

Structured logs include stage-level timing. Identify which stage exceeds expected duration:
- StyleMatcher: expected < 2s
- FactChecker (PubMed + scrape): expected 5-15s
- LLM generation: expected 10-30s

**Step 2 — Check PubMed API latency:**

PubMed E-utilities has known rate limits (3 req/s without API key, 10 req/s with key). If `fact_check` is slow:

```bash
curl -w "%{time_total}s\n" -o /dev/null -s \
  "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=test"
```

If > 5s, PubMed is experiencing latency. The FactChecker will still complete but slowly.

**Step 3 — Check LLM API latency:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 1h | grep "llm_router" | grep "duration_ms"
```

If Claude 3.5 Sonnet p95 > 30s, the LLM router will be hitting the fallback (GPT-4o) — check if OpenAI latency is also elevated.

---

### 2.4 LLM Error Rate Critical

**Alert:** LLM request error rate > 10% over 5 minutes

**Grafana:** `http://localhost:3000/d/llm_costs` → "LLM error rate" panel

**Step 1 — Identify which provider is failing:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 10m | grep -E "anthropic|openai" | grep "error\|exception"
```

**Step 2 — Anthropic API down:**

Check status: https://status.anthropic.com

If Anthropic is down, the LLM router will fall back to GPT-4o automatically. Verify fallback is working:

```bash
# Confirm GPT-4o responses appearing in logs
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 10m | grep "openai" | grep "model=gpt-4"
```

**Step 3 — Both providers down / rate-limited:**

If both LLMs are unavailable, `generate_draft` tasks will fail after retry exhaustion. New `/draft` commands will fail silently (Slack receives no response within Slack's 3s window, n8n will retry).

Immediate action: notify physician that generation is temporarily unavailable.

**Step 4 — API key invalid or quota exceeded:**

```bash
# Test Anthropic key directly
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-5-sonnet-20241022","max_tokens":10,"messages":[{"role":"user","content":"test"}]}'
```

HTTP 401 = invalid key. HTTP 429 = rate limit / quota. Update `.env` and restart affected containers.

---

## 3. Common Failure Scenarios

### 3.1 `/draft` command returns no response in Slack

**Symptoms:** Physician types `/draft topic`, Slack shows "Timed out" or no response.

**Diagnostic flow:**

```bash
# 1. Check backend is reachable
curl http://localhost:8001/health

# 2. Check n8n webhook is configured and active
# Open http://localhost:5678 → Workflows → main_draft_flow → verify "Active" toggle is ON

# 3. Check if request reached FastAPI
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs backend --since 5m | grep "POST /slack/commands"

# 4. If request reached backend, check if task was enqueued
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec redis redis-cli LLEN seratonin_tasks
```

**Common causes:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| No log entry in backend | n8n webhook not triggering | Re-activate n8n workflow; check Slack slash command URL points to n8n |
| Log entry but task not in queue | Redis unavailable | `docker compose ... up -d redis` |
| Task in queue but no processing | Worker down | `docker compose ... up -d worker` |
| Task processed but no Slack message | Slack bot token expired | Regenerate token in Slack app settings, update `SLACK_BOT_TOKEN` in `.env`, restart backend |

---

### 3.2 Draft generated but Publish button does nothing

**Symptoms:** Block Kit card appears in Slack, physician clicks Publish, nothing happens.

```bash
# Check if interaction reached backend
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs backend --since 5m | grep "POST /slack/interactions"

# Check if publish_post task was enqueued
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --since 5m | grep "publish_post"

# Check n8n publishing workflow status
# Open http://localhost:5678 → Executions → look for recent telegram/twitter/threads workflow runs
```

**Common causes:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| No interaction log | Slack Interactive Components URL misconfigured | Verify URL in Slack app settings → Interactivity → Request URL |
| Interaction received, no task | `publish_post` not enqueued | Check error_handler logs for domain exceptions |
| Task enqueued, n8n not triggered | n8n publishing workflow inactive | Activate the relevant workflow in n8n |
| n8n triggered, platform API fails | Expired platform credentials | Update credentials in n8n → Credentials |

---

### 3.3 Worker container keeps restarting

```bash
# Check exit code and last log lines
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  logs worker --tail 50

# Common causes by exit code:
# Exit 1 — Python import error or missing env variable
# Exit 137 — OOM kill (worker using too much memory)
# Exit 143 — SIGTERM (normal shutdown signal)
```

**If OOM kill (exit 137):**

```bash
# Check memory usage
docker stats worker --no-stream

# HuggingFace / FastEmbed model cache may not be persisting
# Verify model_cache volume is mounted:
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec worker ls /app/cache/huggingface
```

If the cache directory is empty, models are re-downloaded on every start and consume peak RAM. Verify the `model_cache` named volume exists on the host:

```bash
docker volume inspect model_cache
```

If missing: `docker volume create model_cache`, then recreate the worker container.

---

### 3.4 Migrations fail on deploy

```bash
# Run migration manually with full output
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic upgrade head

# Check current migration state
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic current

# Check migration history
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic history
```

**If migration conflicts (two heads):**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic merge heads -m "merge_heads"
alembic upgrade head
```

**If migration fails mid-way (partial apply):**

Alembic does not auto-rollback DDL on all databases. Check which statements were applied, then either complete manually in psql or roll back to the previous revision:

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic downgrade -1
```

---

### 3.5 Qdrant collection missing / RAG returning empty results

**Symptoms:** Generation succeeds but content has no style matching or uses no medical facts. Worker logs show `retrieved 0 chunks`.

```bash
# Check Qdrant collections exist
curl http://localhost:6333/collections

# Check collection sizes
curl http://localhost:6333/collections/doctor_style
curl http://localhost:6333/collections/medical_knowledge
```

If collections are empty or missing, the knowledge base needs to be re-indexed:

```bash
# Re-index (runs inside backend container to access Qdrant on internal network)
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend python scripts/index_knowledge_base.py
```

If Qdrant data volume was lost (e.g. host volume deleted), vectors must be rebuilt from source documents in `knowledge_base/`. Indexing takes 5-20 minutes depending on corpus size.

---

## 4. Diagnostic Commands

**Full container status:**
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml ps
```

**Tail logs for a specific service:**
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml logs -f [service]
# service: backend | worker | scheduler | postgres | redis | qdrant | n8n
```

**Check Redis queue depth:**
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec redis redis-cli LLEN seratonin_tasks
```

**Check a specific Taskiq task result:**
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec redis redis-cli GET taskiq:result:<task_id>
```

**Check PostgreSQL draft statuses:**
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec postgres psql -U seratonin -d seratonin_db \
  -c "SELECT id, topic, status, created_at FROM drafts ORDER BY created_at DESC LIMIT 20;"
```

**Check Qdrant collection counts:**
```bash
curl -s http://localhost:6333/collections/doctor_style | python3 -m json.tool | grep vectors_count
curl -s http://localhost:6333/collections/medical_knowledge | python3 -m json.tool | grep vectors_count
```

**Verify n8n health:**
```bash
curl http://localhost:5678/healthz
```

**Check Prometheus targets (all should be UP):**
```bash
curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool | grep -A2 "health"
```

---

## 5. Routine Maintenance

### Weekly

**Review Grafana LLM costs dashboard:**

Open `http://localhost:3000/d/llm_costs`. Check token usage trend. If tokens per draft are increasing, review recent prompt template changes or fact-checker verbosity.

**Prune Docker build cache:**

```bash
docker system prune -f
# To also remove unused images:
docker image prune -a -f
```

**Verify all n8n workflows are active:**

Open `http://localhost:5678 → Workflows`. All production workflows should show the green "Active" indicator.

### Monthly

**Rotate API keys:**

1. Generate new keys in Anthropic Console and OpenAI Platform
2. Update `.env` on the VPS
3. Restart backend and worker: `docker compose ... restart backend worker`
4. Verify generation works end-to-end with a test `/draft`

**Check Alembic migration drift:**

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  run --rm backend alembic check
```

Should output `No new upgrade operations detected` if models and migrations are in sync.

**Review Qdrant collection sizes:**

A growing `doctor_style` collection indicates the feedback loop is working (published posts are being vectorized). Review periodically to ensure quality — if poor-quality posts were published, they should be removed from the collection to avoid degrading future generation.

### On Dependency Update

After updating any package in `pyproject.toml`:

1. Run full test suite locally: `poetry run pytest`
2. Check coverage has not dropped below 95%
3. Push to a feature branch — lint and test CI must pass before merging to `main`
4. Merge to `main` triggers automated build and deploy

---

## 6. Emergency Procedures

### Full System Restart

```bash
# Bring everything down (preserves volumes)
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml down

# Bring everything back up
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d

# Verify health
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml ps
```

### Rollback to Previous Commit

If a broken build was deployed:

```bash
# On the VPS
cd ~/SEROTONIN_SCRIPT
git log --oneline -5          # find the last known-good SHA
git checkout <sha>
bash scripts/deploy.sh
```

The automated `deploy.yml` workflow runs `git pull origin main` before `deploy.sh`, so rollback must be done manually on the VPS by checking out the previous commit.

### Redis Data Loss

If the Redis volume is lost (task queue and result cache):

- In-progress Taskiq tasks are lost — they will not be retried automatically
- Rate limit counters reset — no immediate impact
- `/draft` commands that were in-flight will show no response in Slack

Resolution: restart all services (`docker compose ... up -d`). Redis will start empty. Affected physician workflows will need to re-issue `/draft` commands.

### PostgreSQL Backup and Restore

Backup:
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec postgres pg_dump -U seratonin seratonin_db > backup_$(date +%Y%m%d).sql
```

Restore:
```bash
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml \
  exec -i postgres psql -U seratonin seratonin_db < backup_20250101.sql
```

### Qdrant Backup

Qdrant supports snapshot-based backups via API:

```bash
# Create snapshot
curl -X POST http://localhost:6333/collections/doctor_style/snapshots

# List snapshots
curl http://localhost:6333/collections/doctor_style/snapshots
```

Snapshots are stored inside the Qdrant container at `/qdrant/storage/snapshots/`. Copy to host:

```bash
docker cp qdrant:/qdrant/storage/snapshots/doctor_style ./qdrant_backup_$(date +%Y%m%d)
```