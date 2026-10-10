import logging
import time
from contextlib import asynccontextmanager

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.api.agent import router as agent_router
from app.api.agent import explanation_router
from app.api.model_spec import router as model_spec_router
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
from app.api.metrics import router as metrics_router
from app.api.audit import router as audit_router
from app.api.backups import router as backups_router
from app.api.sso import router as sso_router
from app.api.scim import router as scim_router
from app.api.org_lifecycle import router as org_lifecycle_router
from app.api.solver_licences import router as solver_licences_router
from app.api.suites import router as suites_router
from app.api.run_events import router as run_events_router
from app.api.genui import router as genui_router
from app.api.distances import router as distances_router
from app.api.spatial_ops import router as spatial_ops_router
from app.api.bulk import router as bulk_router
from app.api.candidates import router as candidates_router
from app.api.grids import router as grids_router
from app.api.run_map import router as run_map_router
from app.api.answer_map import router as answer_map_router
from app.api.run_export import router as run_export_router
from app.api.time_ops import router as time_ops_router
from app.api.run_promote import router as run_promote_router
from app.api.hierarchies import router as hierarchies_router
from app.api.data_checks import router as data_checks_router
from app.api.referrers import router as referrers_router
from app.api.workbook import router as workbook_router
from app.api.workbench import router as workbench_router
from app.api.history import router as history_router
from app.api.runs import router as runs_router
from app.api.approvals import router as approvals_router
from app.api.drafts import router as drafts_router
from app.api.layouts import router as layouts_router
from app.api.drawing_layouts import router as drawing_layouts_router
from app.api.organizations import router as organizations_router
from app.api.integrations import router as integrations_router
from app.api.imports import router as imports_router
from app.api.notices import router as notices_router
from app.api.source_refresh import router as source_refresh_router
from app.api.preflight import router as preflight_router
from app.api.workflow import router as workflow_router
from app.api.predictors import router as predictors_router
from app.api.derive import router as derive_router
from app.api.gis import router as gis_router
from app.api.eta import router as eta_router
from app.api.settings import router as settings_router
from app.api.relationships import router as relationships_router
from app.api.routers import router as crud_router
from app.api.start import router as start_router
from app.api.people import router as people_router
from app.api.learned import router as learned_router
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


_SECRET_KEY = __import__("re").compile(r"pass(word|wd)?|secret|token|credential|api_?key|private_?key", __import__("re").I)


def _redacted(value):
    """A request body as a validation error may echo it, with every secret-named value hidden."""
    if isinstance(value, dict):
        return {k: ("***" if isinstance(k, str) and _SECRET_KEY.search(k) else _redacted(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redacted(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_errors(_request: Request, exc: RequestValidationError):
    """FastAPI's 422, without echoing a password, token or key that came with the request (the source test of
    7 October 2026: a connection body missing one field came back with its database password in "input")."""
    errors = []
    for error in exc.errors():
        error = dict(error)
        if "input" in error:
            last = next((str(x) for x in reversed(error.get("loc") or ()) if isinstance(x, str)), "")
            error["input"] = "***" if _SECRET_KEY.search(last) else _redacted(error["input"])
        errors.append(error)
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))


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
app.include_router(predictors_router)
app.include_router(derive_router)
app.include_router(gis_router)
app.include_router(eta_router)
app.include_router(model_spec_router)  # /problems/from-spec, before /problems/{id}
app.include_router(problems_router)
app.include_router(runs_router)
app.include_router(approvals_router)
app.include_router(drafts_router)
app.include_router(layouts_router)
app.include_router(drawing_layouts_router)
app.include_router(organizations_router)
app.include_router(integrations_router)
app.include_router(imports_router)
app.include_router(source_refresh_router)
app.include_router(notices_router)
app.include_router(preflight_router)
app.include_router(workflow_router)
app.include_router(run_events_router)
app.include_router(genui_router)
app.include_router(grids_router)
app.include_router(distances_router)
app.include_router(spatial_ops_router)
app.include_router(bulk_router)
app.include_router(candidates_router)
app.include_router(run_map_router)
app.include_router(answer_map_router)
app.include_router(run_export_router)
app.include_router(time_ops_router)
app.include_router(run_promote_router)
app.include_router(hierarchies_router)
app.include_router(data_checks_router)
app.include_router(referrers_router)
app.include_router(workbook_router)
app.include_router(workbench_router)
app.include_router(history_router)
app.include_router(quota_router)
app.include_router(metrics_router)
app.include_router(audit_router)
app.include_router(backups_router)
app.include_router(sso_router)
app.include_router(scim_router)
app.include_router(org_lifecycle_router)
app.include_router(solver_licences_router)
app.include_router(suites_router)
app.include_router(api_keys_router)
app.include_router(settings_router)
# Re-mounted in Task 7. Task 1 had unmounted it because every query behind
# it read the v0 domain.* tables that migration 0006_schema_v1_domain
# dropped; app/graph/service.py is now written against schema v1, and the
# route moved from /api/graph/domain to /api/v1/graph with it.
app.include_router(graph_router)
app.include_router(start_router)
app.include_router(people_router)
app.include_router(learned_router)
app.include_router(agent_router)
app.include_router(explanation_router)
app.include_router(crud_router)
