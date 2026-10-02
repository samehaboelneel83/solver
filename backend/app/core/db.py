import anyio
import clickhouse_connect
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# A request's connection is taken and given back off the handlers' thread pool
# (`get_db`, below). When both ran on it, a burst larger than the pool filled
# every one of its 40 threads with a request waiting to connect, and the
# requests holding connections had no thread left to finish on: all waited
# out the pool timeout (60 concurrent writes: 40 of them a 500 after 30 s).
# Postgres allows 100; the worker's own pool is lazy and holds a few.
POOL_SIZE, POOL_OVERFLOW, POOL_TIMEOUT_S = 20, 20, 10

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,
    max_overflow=POOL_OVERFLOW,
    # Genuine overload fails fast, as a 503 (`app.main`), not after 30 s.
    pool_timeout=POOL_TIMEOUT_S,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# The role API requests act as (migration 0032): row-level security applies
# to it, where the connecting role bypasses it -- `solver_runtime` (0037,
# BYPASSRLS but not a superuser), or the owner when `.env.runtime` is absent.
REQUEST_ROLE = "solver_app"


@event.listens_for(engine, "checkout")
def _forget_the_last_tenant(dbapi_connection, _record, _proxy) -> None:
    """Every connection leaves the pool as system code: its own role, no
    organization. A request that set a tenant cannot hand it to whatever
    borrows the connection next -- the worker, the seed, another request."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("RESET ROLE")
        cursor.execute("SELECT set_config('app.org_id', '', false)")
        cursor.execute("SELECT set_config('app.actor', '', false)")
    finally:
        cursor.close()
    dbapi_connection.commit()


class Base(DeclarativeBase):
    pass


# Taking a connection and giving it back each have their own threads. A connect
# waiting on an empty pool holds a connect thread -- never a thread a handler
# needs to finish, nor one a finished request needs to give its connection
# back (sharing either one was the same deadlock again, one pool over).
_CONNECT_LIMITER = anyio.CapacityLimiter(POOL_SIZE + POOL_OVERFLOW)
_RELEASE_LIMITER = anyio.CapacityLimiter(POOL_SIZE + POOL_OVERFLOW)


def _release(db: Session, connection) -> None:
    db.close()
    connection.close()


async def get_db():
    """A request's session, on ONE connection for the whole request.

    A plain session hands its connection back to the pool at every commit
    and takes whichever comes next. The tenant a request sets
    (`enter_tenant`) is a property of the connection, so on a plain session
    it would silently vanish after the first commit -- and the next
    statement would run as the superuser, seeing every tenant. Binding the
    session to one connection is what makes the tenant last.
    """
    connection = await anyio.to_thread.run_sync(engine.connect, limiter=_CONNECT_LIMITER)
    db = Session(bind=connection, autoflush=False)
    try:
        yield db
    finally:
        await anyio.to_thread.run_sync(_release, db, connection, limiter=_RELEASE_LIMITER)


def enter_tenant(db: Session, organization_id) -> None:
    """Act as `REQUEST_ROLE` for `organization_id` for the rest of this
    request. Committed at once: a `SET` inside a transaction that later
    rolls back would be undone with it."""
    db.execute(text(f"SET ROLE {REQUEST_ROLE}"))
    db.execute(text("SELECT set_config('app.org_id', :o, false)"), {"o": str(organization_id)})
    db.commit()


def get_clickhouse_client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_db,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )
