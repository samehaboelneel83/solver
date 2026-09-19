"""Shape of the database after migration 0006_schema_v1_domain.

Replaces the deleted test_migrations_domain_{a,b,c}.py and
test_migrations_problem.py, which asserted the v0 schemas that 0006 drops.
"""

from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings

V1_DOMAIN_TABLES = {
    "domain",
    "entity_type",
    "attribute_def",
    "entity",
    "relationship_type",
    "relationship",
    "parameter_def",
    "parameter_value",
}


def _engine():
    return create_engine(get_settings().database_url)


def test_v1_domain_tables_exist_in_public():
    inspector = inspect(_engine())
    assert V1_DOMAIN_TABLES.issubset(set(inspector.get_table_names(schema="public")))


def test_v0_domain_and_problem_schemas_are_gone():
    """0006 drops both schemas wholesale; the four `iam` tables stay put."""
    inspector = inspect(_engine())
    schemas = set(inspector.get_schema_names())
    assert "domain" not in schemas
    assert "problem" not in schemas
    assert {"organization", "user_account", "role", "user_role"}.issubset(
        set(inspector.get_table_names(schema="iam"))
    )


def test_v1_primary_keys_are_bigint_identity():
    """No UUIDs in v1: every surrogate key is
    `bigint GENERATED ALWAYS AS IDENTITY`."""
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, data_type, is_identity, identity_generation "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'id' "
                "AND table_name = ANY(:tables)"
            ),
            {"tables": sorted(V1_DOMAIN_TABLES - {"parameter_value"})},
        ).all()

    assert len(rows) == len(V1_DOMAIN_TABLES) - 1  # parameter_value has a composite PK
    for row in rows:
        assert row.data_type == "bigint", row.table_name
        assert row.is_identity == "YES", row.table_name
        assert row.identity_generation == "ALWAYS", row.table_name


def test_v1_enums_functions_and_indexes_exist():
    with _engine().connect() as conn:
        enums = set(
            conn.execute(
                text("SELECT typname FROM pg_type WHERE typname IN ('entity_role', 'attr_type')")
            ).scalars()
        )
        functions = set(
            conn.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE proname IN "
                    "('entity_validate', 'relationship_validate', 'parameter_value_validate', "
                    "'parameter_value_cleanup', 'entity_descendants')"
                )
            ).scalars()
        )
        indexes = set(
            conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE indexname IN "
                    "('entity_attrs_gin', 'relationship_to_idx', 'parameter_value_entities_gin')"
                )
            ).scalars()
        )

    assert enums == {"entity_role", "attr_type"}
    assert functions == {
        "entity_validate",
        "relationship_validate",
        "parameter_value_validate",
        "parameter_value_cleanup",
        "entity_descendants",
    }
    assert indexes == {"entity_attrs_gin", "relationship_to_idx", "parameter_value_entities_gin"}


def test_entity_descendants_signature_is_stable():
    """Task 7 calls entity_descendants(p_entity bigint, p_rel_type bigint)
    for hierarchy traversal -- pin the signature it will bind against."""
    with _engine().connect() as conn:
        signature = conn.execute(
            text(
                "SELECT pg_get_function_arguments(oid) || ' -> ' || pg_get_function_result(oid) "
                "FROM pg_proc WHERE proname = 'entity_descendants'"
            )
        ).scalar_one()

    assert signature == (
        "p_entity bigint, p_rel_type bigint -> TABLE(entity_id bigint, depth integer)"
    )


def _plan(conn, predicate: str) -> str:
    """The plan Postgres chooses for `SELECT * FROM parameter_value WHERE
    <predicate>`, with sequential scans penalised so the question asked is
    "*can* this predicate reach the index", not "is the table big enough
    today that the planner bothers". `solver_test` holds a handful of
    cells, so without `enable_seqscan = off` both forms would seq-scan and
    the test would pass either way -- i.e. prove nothing."""
    conn.execute(text("SET LOCAL enable_seqscan = off"))
    rows = conn.execute(
        text(f"EXPLAIN (COSTS OFF) SELECT * FROM parameter_value WHERE {predicate}")
    ).scalars()
    return "\n".join(rows)


def test_parameter_value_cleanup_can_use_the_gin_index():
    """Amendment (d). `parameter_value_entities_gin` exists for exactly one
    query -- the DELETE inside `parameter_value_cleanup`, which fires FOR
    EACH ROW on entity delete -- and the supplied DDL's `OLD.id = ANY
    (entity_ids)` cannot use it: `= ANY (<array column>)` has no GIN
    `array_ops` strategy, so the index had no possible user and every
    deleted entity scanned the whole table.

    Two assertions, because either alone is weak. The first pins the
    function body, which is what a future edit would change. The second
    pins *why* the body has to say that, by showing the two predicates
    reach different plans -- so the test still discriminates if someone
    decides the operators are interchangeable and swaps one back."""
    with _engine().connect() as conn:
        body = conn.execute(
            text(
                "SELECT pg_get_functiondef(oid) FROM pg_proc "
                "WHERE proname = 'parameter_value_cleanup'"
            )
        ).scalar_one()

        indexable = _plan(conn, "entity_ids @> ARRAY[1::bigint]")
        not_indexable = _plan(conn, "1 = ANY (entity_ids)")

    assert "entity_ids @> ARRAY[OLD.id]" in body
    assert "= ANY" not in body

    assert "parameter_value_entities_gin" in indexable, indexable
    # The old form, kept here as the discriminator: even with seq scans
    # priced at 1e10 the planner has no index path for it.
    assert "parameter_value_entities_gin" not in not_indexable, not_indexable
    assert "Seq Scan" in not_indexable, not_indexable
