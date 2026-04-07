set -e

echo "🚀 Starting Production Deployment..."

# 1. Очищення старих контейнерів Seratonin (якщо вони є)
# Ми використовуємо назву проекту 'seratonin', щоб не зачепити сторонні бази
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml down --remove-orphans

# 2. Збірка нових образів
echo "📦 Building images..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d --build

# 3. Запуск бази даних та перевірка здоров'я
echo "🗄️ Starting Database..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d postgres redis

# 4. Запуск міграцій через існуючий скрипт
echo "Running migrations..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml run --rm backend bash scripts/migrate.sh

# 5. Повний запуск системи з масштабуванням
echo "🔌 Starting all services..."
docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d

echo "✅ Deployment complete!"