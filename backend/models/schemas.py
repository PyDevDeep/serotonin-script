from datetime import datetime
from typing import Any, List, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import DraftStatus, Platform, TaskStatus


# --- Base Configuration ---
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- User Schemas ---
class UserBase(BaseModel):
    username: str = Field(..., max_length=255)


class UserCreate(UserBase):
    pass


class UserResponse(UserBase, ORMModel):
    id: int
    created_at: datetime


# --- Draft Schemas ---
class DraftBase(BaseModel):
    topic: str = Field(..., max_length=255)


class DraftCreate(DraftBase):
    user_id: int


class DraftUpdate(BaseModel):
    content: Optional[str] = None
    status: Optional[DraftStatus] = None


class DraftResponse(DraftBase, ORMModel):
    id: int
    user_id: int
    content: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


# --- Published Post Schemas ---
class PublishedPostBase(BaseModel):
    platform: Platform
    post_url: str = Field(..., max_length=500)


class PublishedPostCreate(PublishedPostBase):
    draft_id: int


class PublishedPostResponse(PublishedPostBase, ORMModel):
    id: int
    draft_id: int
    published_at: datetime


# --- Feedback Schemas ---
class FeedbackBase(BaseModel):
    comment: str


class FeedbackCreate(FeedbackBase):
    draft_id: int
    user_id: int


class FeedbackResponse(FeedbackBase, ORMModel):
    id: int
    draft_id: int
    user_id: int
    created_at: datetime


# --- Task Result Schemas ---
class TaskResultResponse(ORMModel):
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


# Використовуємо функціональний синтаксис для підтримки ключа 'pass'
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
