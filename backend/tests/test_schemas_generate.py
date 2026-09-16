import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.generate import make_crud_schemas


class _ScratchBase(DeclarativeBase):
    pass


class DummyModel(_ScratchBase):
    __tablename__ = "dummy_model"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _schemas():
    return make_crud_schemas(
        DummyModel, name="Dummy", readonly={"id"}, server_default={"created_at"}
    )


def test_readonly_fields_excluded_from_create_and_update_but_present_in_read():
    Create, Update, Read = _schemas()
    assert "id" not in Create.model_fields
    assert "id" not in Update.model_fields
    assert "id" in Read.model_fields


def test_required_vs_optional_on_create():
    Create, _, _ = _schemas()
    assert Create.model_fields["name"].is_required()
    assert not Create.model_fields["note"].is_required()
    assert not Create.model_fields["created_at"].is_required()


def test_all_non_readonly_fields_optional_on_update():
    _, Update, _ = _schemas()
    assert not Update.model_fields["name"].is_required()
    assert not Update.model_fields["note"].is_required()


def test_read_schema_validates_from_orm_instance():
    _, _, Read = _schemas()
    instance = DummyModel(id=uuid.uuid4(), name="hello", note=None, created_at=None)
    read = Read.model_validate(instance)
    assert read.name == "hello"


def test_read_schema_validates_populated_datetime_column():
    # Regression test: sqlalchemy.DateTime's class name is "DateTime", which
    # upper()-cases to "DATETIME", not "TIMESTAMP". If _TYPE_MAP only has a
    # "TIMESTAMP" key, this falls through to the str default and any real
    # datetime value fails Read.model_validate() with a ValidationError.
    _, _, Read = _schemas()
    now = datetime.now(timezone.utc)
    instance = DummyModel(id=uuid.uuid4(), name="hello", note=None, created_at=now)
    read = Read.model_validate(instance)
    assert isinstance(read.created_at, datetime)
    assert read.created_at == now


class DummyModelWithAliasedColumn(_ScratchBase):
    """Some real tables (relationship_type, time_period) have a column
    literally named "metadata", which collides with SQLAlchemy's reserved
    Base.metadata attribute. The fix is to alias the Python attribute
    (metadata_) while keeping the DB column name (metadata). This model
    reproduces that shape so the generator is proven to key off the
    attribute name, not the column name.
    """

    __tablename__ = "dummy_model_aliased"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", String(255), nullable=True)


def test_aliased_column_uses_attribute_name_not_db_column_name():
    Create, _, Read = make_crud_schemas(
        DummyModelWithAliasedColumn, name="DummyAliased", readonly={"id"}
    )
    assert "metadata_" in Create.model_fields
    assert "metadata" not in Create.model_fields

    instance = DummyModelWithAliasedColumn(id=uuid.uuid4(), metadata_="tag=1")
    read = Read.model_validate(instance)
    assert read.metadata_ == "tag=1"
