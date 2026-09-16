from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import SessionLocal, get_clickhouse_client

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict:
    result = {"postgres": "ok", "clickhouse": "ok"}

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        result["postgres"] = "error"

    try:
        client = get_clickhouse_client()
        client.command("SELECT 1")
    except Exception:
        result["clickhouse"] = "error"

    return result
