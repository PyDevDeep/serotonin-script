from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Liveness probe - перевіряє, чи живий процес FastAPI."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check():
    """
    Readiness probe - тут пізніше буде перевірка
    підключення до БД, Redis та Qdrant.
    """
    return {"status": "ready"}
