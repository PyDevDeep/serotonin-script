from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config.settings import settings
from backend.repositories.draft_repository import DraftRepository
from backend.repositories.feedback_repository import FeedbackRepository

# Для роботи всередині Docker-мережі використовуємо внутрішній хост та порт
DATABASE_URL = f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
async_session_maker = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency для отримання сесії БД."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_draft_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DraftRepository:
    """Dependency для ін'єкції DraftRepository."""
    return DraftRepository(session)


def get_feedback_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackRepository:
    """Dependency для ін'єкції FeedbackRepository."""
    return FeedbackRepository(session)
