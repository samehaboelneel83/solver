from fastapi import FastAPI

from app.api.health import router as health_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import get_clickhouse_client

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)


@app.on_event("startup")
def on_startup() -> None:
    create_analytics_schema(get_clickhouse_client())
