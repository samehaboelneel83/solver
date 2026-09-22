import clickhouse_connect
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# The role API requests act as (migration 0032): row-level security applies
# to it, where the connecting role -- a superuser -- bypasses it.
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
    finally:
        cursor.close()
    dbapi_connection.commit()


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    """A request's session, on ONE connection for the whole request.

    A plain session hands its connection back to the pool at every commit
    and takes whichever comes next. The tenant a request sets
    (`enter_tenant`) is a property of the connection, so on a plain session
    it would silently vanish after the first commit -- and the next
    statement would run as the superuser, seeing every tenant. Binding the
    session to one connection is what makes the tenant last.
    """
    connection = engine.connect()
    db = Session(bind=connection, autoflush=False)
    try:
        yield db
    finally:
        db.close()
        connection.close()


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
