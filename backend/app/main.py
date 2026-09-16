import logging

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.meta import router as meta_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin

logger = logging.getLogger(__name__)

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(crud_router)


@app.on_event("startup")
def on_startup() -> None:
    try:
        create_analytics_schema(get_clickhouse_client())
    except Exception:
        logger.exception("Could not create ClickHouse analytics schema; continuing")
    db = SessionLocal()
    try:
        seed_admin(db)
    except Exception:
        db.rollback()
        logger.warning(
            "Skipped admin seeding — have you run `alembic upgrade head`? "
            "Run: docker compose run --rm --no-deps -T backend alembic upgrade head",
            exc_info=True,
        )
    finally:
        db.close()
