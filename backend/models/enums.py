from enum import Enum


class Platform(str, Enum):
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    THREADS = "threads"


class DraftStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    REJECTED = "rejected"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
