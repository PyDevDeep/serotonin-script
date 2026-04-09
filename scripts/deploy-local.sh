#!/bin/bash
set -e

# Локальний деплой: білдить образи прямо на VPS (без GHCR).
# Використовуй коли немає доступу до GHCR або для швидкого тесту на сервері.

echo "Starting Local Build Deployment..."

# 1. Зупинка старих контейнерів
docker compose -f docker-compose.yml -f infra/docker-compose.prod.local.yml down --remove-orphans

# 2. Збірка і запуск нових образів
echo "Building images..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.local.yml up -d --build

# 3. Запуск міграцій БД
echo "Running migrations..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.local.yml run --rm backend bash scripts/migrate.sh

# 4. Очищення dangling образів
echo "Cleaning up..."
docker image prune -f

echo "Local deployment complete!"
