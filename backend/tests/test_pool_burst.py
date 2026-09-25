"""A burst of concurrent writes queues, never waits out the pool: 120 concurrent creates -- three
times the request threads -- each answered 201. Before, 60 answered 40 with a 500 after 30 s, and
a pool as wide as the threads only moved the line to 100 (`app.core.db`)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core import db as db_module
from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_a_burst_three_times_the_threads_all_succeed(tenants, db):  # noqa: F811
    """On one event loop and its own thread pool, as the server runs them -- TestClient would
    serialize the requests and never fill the pool."""
    import asyncio

    import httpx

    headers, domain = tenants["a"], tenants["domain_a"]
    item = TestClient(app).post("/api/v1/entity-types", json={"domain_id": domain, "name": "item", "role": "other"},
                                headers=headers).json()

    async def burst():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            answers = await asyncio.gather(*(
                client.post("/api/v1/entities", json={"entity_type_id": item["id"], "key": f"k{i}"}, headers=headers)
                for i in range(120)))
        return [a.status_code for a in answers]

    started = time.monotonic()
    statuses = asyncio.run(burst())
    assert statuses == [201] * 120
    assert time.monotonic() - started < db_module.POOL_TIMEOUT_S


def test_an_exhausted_pool_is_a_503_to_retry(tenants, monkeypatch):  # noqa: F811
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    def exhausted():
        raise PoolTimeout("QueuePool limit reached")
        yield  # pragma: no cover

    from app.core.db import get_db

    app.dependency_overrides[get_db] = exhausted
    try:
        response = TestClient(app).get("/api/v1/entity-types", headers=tenants["a"])
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
