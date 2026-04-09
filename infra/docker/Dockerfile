# Stage 1: Builder — збираємо залежності
FROM python:3.13-slim AS builder

WORKDIR /app
ENV POETRY_VERSION=2.0.1

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION" poetry-plugin-export
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt --without dev

# Stage 2: Base — спільне середовище для всіх сервісів
FROM python:3.13-slim AS base

WORKDIR /app
ENV PYTHONPATH=/app

RUN groupadd -r seratonin && useradd -r -g seratonin seratonin

COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN apt-get update && apt-get install -y --no-install-recommends netcat-openbsd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cache/huggingface /app/cache/fastembed \
    && chown -R seratonin:seratonin /app
USER seratonin

# ==========================================
# Stage 3: Індивідуальні точки входу (Targets)
# ==========================================

# Target: Backend
FROM base AS backend
EXPOSE 8001
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]

# Target: Worker
FROM base AS worker
EXPOSE 9000
CMD ["taskiq", "worker", "backend.workers.broker:broker", "backend.workers.tasks"]

# Target: Scheduler
FROM base AS scheduler
EXPOSE 9001
CMD ["taskiq", "scheduler", "backend.workers.broker:scheduler", "backend.workers.tasks"]