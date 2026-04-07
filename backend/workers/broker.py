from typing import Any

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend, RedisScheduleSource

from backend.config.settings import settings
from backend.workers.middlewares.logging import StructlogMiddleware
from backend.workers.middlewares.metrics import PrometheusMetricsMiddleware
from backend.workers.middlewares.retry import RetryTrackerMiddleware

redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"

# Initialise the broker with an explicit queue name
broker = ListQueueBroker(redis_url, queue_name="seratonin_tasks")

result_backend: RedisAsyncResultBackend[Any] = RedisAsyncResultBackend(
    redis_url, result_ex_time=3600
)
broker.with_result_backend(result_backend)

broker.add_middlewares(
    StructlogMiddleware(),
    RetryTrackerMiddleware(),
    PrometheusMetricsMiddleware(),
)

# Initialise the scheduler with label and Redis sources
redis_source = RedisScheduleSource(redis_url)
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker), redis_source],
)
