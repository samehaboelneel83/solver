from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.meta import router as meta_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(crud_router)


@app.on_event("startup")
def on_startup() -> None:
    create_analytics_schema(get_clickhouse_client())
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
