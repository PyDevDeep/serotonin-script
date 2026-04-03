from typing import Any

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from backend.config.settings import settings
from backend.workers.middlewares.logging import StructlogMiddleware
from backend.workers.middlewares.metrics import PrometheusMetricsMiddleware
from backend.workers.middlewares.retry import RetryTrackerMiddleware

redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"

# Ініціалізуємо брокер з явно вказаною чергою (ізоляція від інших проєктів)
broker = ListQueueBroker(redis_url, queue_name="seratonin_tasks")

# Додаємо явну типізацію для усунення помилок Pylance
result_backend: RedisAsyncResultBackend[Any] = RedisAsyncResultBackend(
    redis_url, result_ex_time=3600
)
broker.with_result_backend(result_backend)

# Підключення Middlewares у правильному порядку
broker.add_middlewares(
    StructlogMiddleware(),
    RetryTrackerMiddleware(),
    PrometheusMetricsMiddleware(),
)
