import logging

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.entities import router as entities_router
from app.api.entity_types import router as entity_types_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.meta import router as meta_router
from app.api.options import router as options_router
from app.api.parameters import router as parameters_router
from app.api.problems import router as problems_router
from app.api.relationships import router as relationships_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin

logger = logging.getLogger(__name__)

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router)
# Must precede crud_router: FastAPI matches routes in registration order,
# and crud_router's GET /api/{schema}/{table}/{item_id} would otherwise
# swallow /options requests, answering 422 "invalid uuid" for the literal
# path segment "options".
app.include_router(options_router)
# Purpose-built schema v1 routers. Mounted before crud_router purely for
# readability -- their /api/v1/... prefix cannot collide with the generic
# routers' literal /api/{table} and /api/iam/{table} prefixes.
app.include_router(entity_types_router)
app.include_router(entities_router)
app.include_router(relationships_router)
app.include_router(parameters_router)
app.include_router(problems_router)
# Re-mounted in Task 7. Task 1 had unmounted it because every query behind
# it read the v0 domain.* tables that migration 0006_schema_v1_domain
# dropped; app/graph/service.py is now written against schema v1, and the
# route moved from /api/graph/domain to /api/v1/graph with it.
app.include_router(graph_router)
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
