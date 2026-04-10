#!/bin/bash
set -e

echo "Starting Production Deployment (GHCR images)..."

# 1. Завантаження найновіших образів із GHCR
echo "Pulling latest images..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml pull

# 2. Перезапуск сервісів (тільки змінені контейнери перестворюються)
echo "Starting / Updating services..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d

# 3. Запуск міграцій БД
echo "Running migrations..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml run --rm backend bash scripts/migrate.sh

# 4. Очищення старих dangling образів
echo "Cleaning up old images..."
docker image prune -f

echo "Deployment complete!"
