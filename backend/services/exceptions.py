from backend.models.enums import Platform


class DomainError(Exception):
    """Base class for all domain-level errors."""


class DraftNotFoundError(DomainError):
    """Raised when a requested draft does not exist."""

    def __init__(self, draft_id: int | str) -> None:
        super().__init__(f"Draft '{draft_id}' not found.")
        self.draft_id = draft_id


class PublishingFailedError(DomainError):
    """Raised when publishing to a social platform fails."""

    def __init__(self, platform: Platform | str, reason: str) -> None:
        super().__init__(f"Publishing to '{platform}' failed: {reason}")
        self.platform = platform
        self.reason = reason


class UnsupportedPlatformError(DomainError):
    """Raised when no publisher is registered for the requested platform."""

    def __init__(self, platform: str) -> None:
        super().__init__(f"No publisher registered for platform '{platform}'.")
        self.platform = platform


class ContentTooLongError(DomainError):
    """Raised when content exceeds the platform's character limit."""

    def __init__(self, platform: Platform | str, limit: int, actual: int) -> None:
        super().__init__(
            f"Content too long for '{platform}': limit {limit}, got {actual}."
        )
        self.platform = platform
        self.limit = limit
        self.actual = actual
