from datetime import datetime
from typing import Any, List, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import DraftStatus, Platform, TaskStatus


# --- Base Configuration ---
class ORMModel(BaseModel):
    """Base Pydantic model with ORM mode enabled."""

    model_config = ConfigDict(from_attributes=True)


# --- User Schemas ---
class UserBase(BaseModel):
    """Shared user fields."""

    username: str = Field(..., max_length=255)


class UserCreate(UserBase):
    """Schema for creating a new user."""


class UserResponse(UserBase, ORMModel):
    """Schema for reading a user record."""

    id: int
    created_at: datetime


# --- Draft Schemas ---
class DraftBase(BaseModel):
    """Shared draft fields."""

    topic: str = Field(..., max_length=255)


class DraftCreate(DraftBase):
    """Schema for creating a new draft."""

    user_id: int
    platform: Platform


class DraftUpdate(BaseModel):
    """Schema for partial updates to a draft."""

    content: Optional[str] = None
    status: Optional[DraftStatus] = None
    platform: Optional[Platform] = None
    scheduled_at: Optional[datetime] = None


class DraftResponse(DraftBase, ORMModel):
    """Schema for reading a draft record."""

    id: int
    user_id: int
    content: Optional[str]
    status: str
    platform: str
    scheduled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# --- Published Post Schemas ---
class PublishedPostBase(BaseModel):
    """Shared fields for a published post."""

    platform: Platform
    post_url: str = Field(..., max_length=500)


class PublishedPostCreate(PublishedPostBase):
    """Schema for creating a published post record."""

    draft_id: int


class PublishedPostResponse(PublishedPostBase, ORMModel):
    """Schema for reading a published post record."""

    id: int
    draft_id: int
    published_at: datetime


# --- Feedback Schemas ---
class FeedbackBase(BaseModel):
    """Shared feedback fields."""

    comment: str


class FeedbackCreate(FeedbackBase):
    """Schema for submitting new feedback."""

    draft_id: int
    user_id: int


class FeedbackResponse(FeedbackBase, ORMModel):
    """Schema for reading a feedback record."""

    id: int
    draft_id: int
    user_id: int
    created_at: datetime


# --- Task Result Schemas ---
class TaskResultResponse(ORMModel):
    """Schema for reading a task result record."""

    id: int
    task_id: str
    status: TaskStatus
    result: Optional[dict[str, Any]]
    created_at: datetime


class PubMedArticle(TypedDict):
    uid: str
    title: str
    abstract: str
    url: str


class JudgeViolation(TypedDict):
    sentence: str
    reason: str


# Use the functional syntax to support the reserved key 'pass'
JudgeResult = TypedDict(
    "JudgeResult", {"pass": bool, "violations": List[JudgeViolation]}
)


# --- Taskiq API Schemas ---
class DraftGenerateRequest(BaseModel):
    """Схема для запиту на генерацію нового драфту"""

    topic: str = Field(..., max_length=255)
    platform: Platform
    source_url: Optional[str] = None
    user_id: int


class TaskResponse(BaseModel):
    """Універсальна схема для статусів та результатів Taskiq"""

    task_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None


# --- n8n webhook schema ---
class PublishConfirmPayload(BaseModel):
    """Payload received from n8n after a successful social media publication."""

    post_id: str
    platform: str
    content: str
