import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.api.api_keys import router as api_keys_router
from app.api.auth import router as auth_router
from app.api.entities import router as entities_router
from app.api.entity_types import router as entity_types_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.meta import router as meta_router
from app.api.options import router as options_router
from app.api.parameters import router as parameters_router
from app.api.problems import router as problems_router
from app.api.quota import router as quota_router
from app.api.solver_licences import router as solver_licences_router
from app.api.run_events import router as run_events_router
from app.api.genui import router as genui_router
from app.api.distances import router as distances_router
from app.api.bulk import router as bulk_router
from app.api.grids import router as grids_router
from app.api.run_map import router as run_map_router
from app.api.runs import router as runs_router
from app.api.settings import router as settings_router
from app.api.relationships import router as relationships_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core import logs, metrics, tracing
from app.core.db import SessionLocal, get_clickhouse_client
from app.core.nul_guard import NulByteGuard
from app.seed import ensure_weekly_rota_template, seed_admin
from app.showcase import ensure_showcase_templates

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # After uvicorn has set up its own logging, so ours replaces it.
    logs.configure("api")
    tracing.configure("api")
    # Internal port only (compose does not publish it): queue depth names
    # organizations. See app.core.metrics.
    metrics.register_queue_depth()
    metrics.serve("API_METRICS_PORT", 9101)
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
    # The weekly_rota template, refreshed like the showcase ones below. It used
    # to be refreshed only by `python -m app.seed`, so a fix to the template
    # never reached a live database.
    db = SessionLocal()
    try:
        ensure_weekly_rota_template(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Skipped the weekly_rota template", exc_info=True)
    finally:
        db.close()
    # The feed-blend and load-balance templates, which show the linear and
    # quadratic solving the rota cannot. Separate from the admin seed so a
    # problem with one does not stop the other.
    db = SessionLocal()
    try:
        ensure_showcase_templates(db)
    except Exception:
        db.rollback()
        logger.warning("Skipped the showcase templates", exc_info=True)
    finally:
        db.close()
    yield


app = FastAPI(title="Problem Solver Platform API", lifespan=lifespan)

_requests = logs.get("solver.api")


@app.middleware("http")
async def log_request(request: Request, call_next):
    """One line per request: what was asked, by which organization, the
    answer's status and how long it took. The organization is known only
    once the request has been authenticated (`get_current_user` puts it on
    `request.state`); a request that never was has none."""
    started = time.perf_counter()
    status = 500
    # The root of any trace a request starts, a submitted run's included:
    # `enqueue_run` records it on the run and the worker continues it.
    with tracing.span(f"{request.method} {request.url.path}", method=request.method) as current:
        try:
            response = await call_next(request)
            status = response.status_code
            current.set_attribute("status", status)
            return response
        finally:
            _log_request(request, status, started)


def _log_request(request: Request, status: int, started: float) -> None:
    _requests.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=status,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        org_id=getattr(request.state, "org_id", None),
        user=getattr(request.state, "username", None),
    )


# Before routing, and so before authentication: a NUL (U+0000) anywhere in
# a query string or a JSON/form body is a 422 naming the field, not the
# unhandled 500 psycopg2's adapter would otherwise produce. Deliberately
# one edge-level guard rather than a rule per field -- see the module
# docstring for why `translate_db_error` cannot cover this case.
app.add_middleware(NulByteGuard)


@app.exception_handler(PoolTimeout)
async def pool_exhausted(_request: Request, _exc: PoolTimeout):
    """Every database connection is busy and none came back in time: the
    platform is overloaded, not the request wrong -- a 503 to retry, never a
    500 traceback (`app.core.db` sizes the pool so a burst queues instead)."""
    return JSONResponse(
        status_code=503,
        content={"detail": "the platform is busy; try again in a moment"},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(DBAPIError)
async def tenancy_errors(_request: Request, exc: DBAPIError):
    """What the tenancy triggers and policies raise (migration 0032), for
    every route rather than each one.

    - P0002: a row names a parent this organization cannot see. It is
      reported exactly as a parent that does not exist has always been --
      a 409 with a string detail -- so a tenant learns nothing about
      another's ids.
    - 42501: a write the caller's organization may not make, such as a
      platform-wide definition by a non-operator -- a 403.

    Anything else is re-raised: a 500 stays a 500.
    """
    code = getattr(exc.orig, "pgcode", "") or ""
    diag = getattr(exc.orig, "diag", None)
    message = getattr(diag, "message_primary", None) or "that does not exist"
    if code == "P0002":
        return JSONResponse(status_code=409, content={"detail": message})
    if code == "42501":
        return JSONResponse(
            status_code=403,
            content={"detail": "this organization may not make that change"},
        )
    raise exc

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
app.include_router(runs_router)
app.include_router(run_events_router)
app.include_router(genui_router)
app.include_router(grids_router)
app.include_router(distances_router)
app.include_router(bulk_router)
app.include_router(run_map_router)
app.include_router(quota_router)
app.include_router(solver_licences_router)
app.include_router(api_keys_router)
app.include_router(settings_router)
# Re-mounted in Task 7. Task 1 had unmounted it because every query behind
# it read the v0 domain.* tables that migration 0006_schema_v1_domain
# dropped; app/graph/service.py is now written against schema v1, and the
# route moved from /api/graph/domain to /api/v1/graph with it.
app.include_router(graph_router)
app.include_router(crud_router)
