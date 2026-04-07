from enum import Enum


class Platform(str, Enum):
    """Supported social media publishing platforms."""

    TELEGRAM = "telegram"
    TWITTER = "twitter"
    THREADS = "threads"


class DraftStatus(str, Enum):
    """Possible lifecycle statuses for a content draft."""

    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    REJECTED = "rejected"


class TaskStatus(str, Enum):
    """Possible statuses for a Taskiq background task."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
