"""0117: the tenant check of the tables that grow large, written for each table instead of read at run time.

`tenant_inherit` (0032) serves every table: for each parent it names, it reads the column from `to_jsonb(NEW)`
and looks the parent up with a dynamic `EXECUTE`. That is 0.09 ms a row -- for the links of a layout, nearly
half of the time to store them (the scale benchmark of 7 October 2026: 50,000 links took 9.3 s, 4.4 s of it here).

For the five tables that hold records, links, cells and a run's results, the same check is generated once per
table with static SQL (planned once, no JSON): the same parents in the same order, the same errors and codes.
The generic function stays for every other table.

`relationship_validate` also asked the type lineage twice per link to learn whether a link could nest, before
looking for the reference field that alone makes a plain link nest; it now looks for that field first (an
index lookup), and asks the lineage only when there is one. The same checks, the same errors.

Three checks of what a statement inserts now run once per statement over all its rows (a transition table),
not once per row: the link checks (kinds match, how many a record may have, no loop), the guard on links a
reference field owns, and the history row of each new record. Updates and deletes keep the row checks.

Together (the scale benchmark): 200,000 links built in 26 s instead of 79 s.
"""
from alembic import op

revision = "0117"
down_revision = "0116"
branch_labels = None
depends_on = None

#: table -> its parents, as its tenant trigger names them: (parent table, column, id type).
HOT = {
    "entity": [("entity_type", "entity_type_id", "bigint")],
    "relationship": [("relationship_type", "relationship_type_id", "bigint"), ("entity", "from_entity_id", "bigint"),
                     ("entity", "to_entity_id", "bigint")],
    "parameter_value": [("parameter_def", "parameter_def_id", "bigint")],
    "constraint_result": [("run", "run_id", "bigint")],
    "run_event": [("run", "run_id", "bigint")],
}


def _function(table: str, parents: list[tuple[str, str, str]]) -> str:
    steps = []
    for parent, column, _ in parents:
        steps.append(f"""
            IF NEW.{column} IS NOT NULL THEN
                SELECT organization_id INTO found FROM {parent} WHERE id = NEW.{column};
                IF found IS NULL THEN
                    RAISE EXCEPTION 'no % with id %', '{parent}', NEW.{column} USING ERRCODE = 'P0002';
                END IF;
                IF org IS NULL THEN
                    org := found;
                ELSIF found <> org THEN
                    RAISE EXCEPTION '% % belongs to another organization', '{parent}', NEW.{column}
                        USING ERRCODE = 'P0002';
                END IF;
            END IF;""")
    return f"""
    CREATE OR REPLACE FUNCTION tenant_inherit_{table}() RETURNS trigger LANGUAGE plpgsql AS $function$
    -- tenant_inherit (0032) for {table}, with static SQL (0117).
    DECLARE found uuid; org uuid;
    BEGIN
        IF TG_OP = 'UPDATE' AND NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
            RAISE EXCEPTION 'a row cannot move to another organization' USING ERRCODE = '23514';
        END IF;{''.join(steps)}
        IF NEW.organization_id IS NULL THEN
            NEW.organization_id := org;
        ELSIF org IS NOT NULL AND NEW.organization_id <> org THEN
            RAISE EXCEPTION 'a row must belong to its parent''s organization' USING ERRCODE = 'P0002';
        END IF;
        RETURN NEW;
    END;
    $function$;
    """


def _trigger(table: str, function: str, args: str = "") -> str:
    return f"""
    DROP TRIGGER IF EXISTS a_{table}_tenant ON {table};
    CREATE TRIGGER a_{table}_tenant BEFORE INSERT OR UPDATE ON {table}
      FOR EACH ROW EXECUTE FUNCTION {function}({args});
    """


def upgrade() -> None:
    for table, parents in HOT.items():
        op.execute(_function(table, parents))
        op.execute(_trigger(table, f"tenant_inherit_{table}"))
    op.execute(r"""
    CREATE OR REPLACE FUNCTION relationship_validate() RETURNS trigger LANGUAGE plpgsql AS $function$
    DECLARE rt relationship_type; v_attr text; v_nested boolean; ft bigint; tt bigint;
    BEGIN
        SELECT * INTO rt FROM relationship_type WHERE id = NEW.relationship_type_id;
        SELECT entity_type_id INTO ft FROM entity WHERE id = NEW.from_entity_id;
        SELECT entity_type_id INTO tt FROM entity WHERE id = NEW.to_entity_id;
        -- The record's own kind first (0110): the lineage is asked only for an inherited kind.
        IF NOT (ft = rt.from_type_id OR entity_type_is_a(ft, rt.from_type_id))
        OR NOT (tt = rt.to_type_id OR entity_type_is_a(tt, rt.to_type_id)) THEN
            RAISE EXCEPTION 'relationship "%": entity types do not match', rt.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'type_mismatch',
                          'field',          rt.name,
                          'from_entity_id', NEW.from_entity_id,
                          'to_entity_id',   NEW.to_entity_id)::text;
        END IF;
        IF rt.cardinality IN ('one_to_many', 'one_to_one') AND EXISTS (
            SELECT 1 FROM relationship r WHERE r.relationship_type_id = rt.id
               AND r.to_entity_id = NEW.to_entity_id AND r.id IS DISTINCT FROM NEW.id) THEN
            RAISE EXCEPTION 'relationship "%": target already has a source', rt.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'cardinality',
                          'field',          rt.name,
                          'cardinality',    rt.cardinality,
                          'to_entity_id',   NEW.to_entity_id)::text;
        END IF;
        IF rt.cardinality IN ('many_to_one', 'one_to_one') AND EXISTS (
            SELECT 1 FROM relationship r WHERE r.relationship_type_id = rt.id
               AND r.from_entity_id = NEW.from_entity_id AND r.id IS DISTINCT FROM NEW.id) THEN
            RAISE EXCEPTION 'relationship "%": source already has a target', rt.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'cardinality',
                          'field',          rt.name,
                          'cardinality',    rt.cardinality,
                          'from_entity_id', NEW.from_entity_id)::text;
        END IF;
        -- A link can nest only when its two ends can be one kind: a hierarchy, or a reference field's
        -- mirror between kinds that inherit from each other. The field first (0117): without one, a plain
        -- link cannot nest, and the lineage is not asked.
        v_nested := rt.is_hierarchy;
        SELECT ad.name INTO v_attr FROM attribute_def ad WHERE ad.references_id = rt.id;
        IF NOT v_nested AND v_attr IS NOT NULL THEN
            v_nested := rt.from_type_id = rt.to_type_id OR entity_type_is_a(rt.from_type_id, rt.to_type_id)
                        OR entity_type_is_a(rt.to_type_id, rt.from_type_id);
        END IF;
        IF v_nested AND (NEW.from_entity_id = NEW.to_entity_id OR EXISTS (
            WITH RECURSIVE down AS (
                SELECT to_entity_id AS id FROM relationship
                 WHERE relationship_type_id = rt.id
                   AND from_entity_id = NEW.to_entity_id
                   AND id IS DISTINCT FROM NEW.id
                UNION
                SELECT r.to_entity_id FROM relationship r JOIN down ON r.from_entity_id = down.id
                 WHERE r.relationship_type_id = rt.id
                   AND r.id IS DISTINCT FROM NEW.id)
            SELECT 1 FROM down WHERE id = NEW.from_entity_id)) THEN
            IF v_attr IS NOT NULL THEN
                RAISE EXCEPTION '%: "%" would make a loop -- it is this record or one below it', v_attr,
                      (SELECT key FROM entity WHERE id = NEW.to_entity_id)
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object(
                              'kind',           'cycle',
                              'field',          v_attr,
                              'record',         (SELECT key FROM entity WHERE id = NEW.from_entity_id),
                              'from_entity_id', NEW.from_entity_id,
                              'to_entity_id',   NEW.to_entity_id)::text;
            END IF;
            RAISE EXCEPTION 'relationship "%": would create a cycle', rt.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'cycle',
                          'field',          rt.name,
                          'from_entity_id', NEW.from_entity_id,
                          'to_entity_id',   NEW.to_entity_id)::text;
        END IF;
        RETURN NEW;
    END
    $function$;
    """)

    # Links added by a statement are checked together, once per statement (0117): the same three checks and
    # errors as the row check, set-based. An update of a link is still checked row by row.
    op.execute(r"""
    CREATE OR REPLACE FUNCTION relationship_validate_added() RETURNS trigger LANGUAGE plpgsql AS $function$
    DECLARE r record; v_attr text; v_nested boolean;
    BEGIN
        SELECT a.from_entity_id, a.to_entity_id, t.name INTO r
          FROM added a JOIN relationship_type t ON t.id = a.relationship_type_id
          JOIN entity f ON f.id = a.from_entity_id JOIN entity x ON x.id = a.to_entity_id
         WHERE NOT (f.entity_type_id = t.from_type_id OR entity_type_is_a(f.entity_type_id, t.from_type_id))
            OR NOT (x.entity_type_id = t.to_type_id OR entity_type_is_a(x.entity_type_id, t.to_type_id))
         LIMIT 1;
        IF FOUND THEN
            RAISE EXCEPTION 'relationship "%": entity types do not match', r.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'type_mismatch',
                          'field',          r.name,
                          'from_entity_id', r.from_entity_id,
                          'to_entity_id',   r.to_entity_id)::text;
        END IF;
        SELECT a.to_entity_id, t.name, t.cardinality INTO r
          FROM added a JOIN relationship_type t ON t.id = a.relationship_type_id
         WHERE t.cardinality IN ('one_to_many', 'one_to_one')
           AND (SELECT count(*) FROM relationship x WHERE x.relationship_type_id = t.id
                   AND x.to_entity_id = a.to_entity_id) > 1
         LIMIT 1;
        IF FOUND THEN
            RAISE EXCEPTION 'relationship "%": target already has a source', r.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'cardinality',
                          'field',          r.name,
                          'cardinality',    r.cardinality,
                          'to_entity_id',   r.to_entity_id)::text;
        END IF;
        SELECT a.from_entity_id, t.name, t.cardinality INTO r
          FROM added a JOIN relationship_type t ON t.id = a.relationship_type_id
         WHERE t.cardinality IN ('many_to_one', 'one_to_one')
           AND (SELECT count(*) FROM relationship x WHERE x.relationship_type_id = t.id
                   AND x.from_entity_id = a.from_entity_id) > 1
         LIMIT 1;
        IF FOUND THEN
            RAISE EXCEPTION 'relationship "%": source already has a target', r.name
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',           'cardinality',
                          'field',          r.name,
                          'cardinality',    r.cardinality,
                          'from_entity_id', r.from_entity_id)::text;
        END IF;
        -- Loops, only for the links that can nest: a hierarchy, or a reference field's mirror between kinds
        -- that inherit from each other.
        FOR r IN SELECT a.id, a.from_entity_id, a.to_entity_id, t.id AS type_id, t.name, t.is_hierarchy,
                        t.from_type_id, t.to_type_id, ad.name AS attr
                   FROM added a JOIN relationship_type t ON t.id = a.relationship_type_id
                   LEFT JOIN attribute_def ad ON ad.references_id = t.id
                  WHERE t.is_hierarchy OR ad.name IS NOT NULL LOOP
            v_attr := r.attr;
            v_nested := r.is_hierarchy OR r.from_type_id = r.to_type_id
                        OR entity_type_is_a(r.from_type_id, r.to_type_id) OR entity_type_is_a(r.to_type_id, r.from_type_id);
            CONTINUE WHEN NOT v_nested;
            IF r.from_entity_id = r.to_entity_id OR EXISTS (
                WITH RECURSIVE down AS (
                    SELECT to_entity_id AS id FROM relationship
                     WHERE relationship_type_id = r.type_id
                       AND from_entity_id = r.to_entity_id
                       AND id IS DISTINCT FROM r.id
                    UNION
                    SELECT x.to_entity_id FROM relationship x JOIN down ON x.from_entity_id = down.id
                     WHERE x.relationship_type_id = r.type_id
                       AND x.id IS DISTINCT FROM r.id)
                SELECT 1 FROM down WHERE id = r.from_entity_id) THEN
                IF v_attr IS NOT NULL THEN
                    RAISE EXCEPTION '%: "%" would make a loop -- it is this record or one below it', v_attr,
                          (SELECT key FROM entity WHERE id = r.to_entity_id)
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object(
                                  'kind',           'cycle',
                                  'field',          v_attr,
                                  'record',         (SELECT key FROM entity WHERE id = r.from_entity_id),
                                  'from_entity_id', r.from_entity_id,
                                  'to_entity_id',   r.to_entity_id)::text;
                END IF;
                RAISE EXCEPTION 'relationship "%": would create a cycle', r.name
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object(
                              'kind',           'cycle',
                              'field',          r.name,
                              'from_entity_id', r.from_entity_id,
                              'to_entity_id',   r.to_entity_id)::text;
            END IF;
        END LOOP;
        RETURN NULL;
    END
    $function$;
    DROP TRIGGER IF EXISTS relationship_validate ON relationship;
    CREATE TRIGGER relationship_validate BEFORE UPDATE ON relationship
      FOR EACH ROW EXECUTE FUNCTION relationship_validate();
    CREATE TRIGGER relationship_validate_added AFTER INSERT ON relationship
      REFERENCING NEW TABLE AS added FOR EACH STATEMENT EXECUTE FUNCTION relationship_validate_added();
    """)

    # A record's history row on insert is written once per statement for all the records it added (0117):
    # 0.9 s of every 20,000 records was this trigger, row by row. Updates and deletes keep the row trigger.
    op.execute(r"""
    CREATE OR REPLACE FUNCTION entity_change_record_added() RETURNS trigger LANGUAGE plpgsql AS $function$
    BEGIN
        INSERT INTO entity_change (organization_id, entity_id, entity_type_id, actor, op, before, after)
        SELECT a.organization_id, a.id, a.entity_type_id, nullif(current_setting('app.actor', true), ''), 'insert',
               NULL, entity_snapshot(a)
          FROM added a;
        RETURN NULL;
    END
    $function$;
    DROP TRIGGER IF EXISTS entity_change_record ON entity;
    CREATE TRIGGER entity_change_record AFTER UPDATE OR DELETE ON entity
      FOR EACH ROW EXECUTE FUNCTION entity_change_record();
    CREATE TRIGGER entity_change_record_added AFTER INSERT ON entity
      REFERENCING NEW TABLE AS added FOR EACH STATEMENT EXECUTE FUNCTION entity_change_record_added();
    """)

    # A link written directly where a reference field owns it is refused once per statement on insert (0117):
    # the field is looked up per kind of link, not per link. Updates and deletes keep the row trigger.
    op.execute(r"""
    CREATE OR REPLACE FUNCTION relationship_reference_guard_added() RETURNS trigger LANGUAGE plpgsql AS $function$
    DECLARE name_ text;
    BEGIN
        IF coalesce(current_setting('solver.reference_sync', true), '') = 'on' THEN
            RETURN NULL;
        END IF;
        SELECT ad.name INTO name_
          FROM (SELECT DISTINCT relationship_type_id FROM added) a
          JOIN attribute_def ad ON ad.references_id = a.relationship_type_id
          JOIN relationship_type t ON t.id = a.relationship_type_id
         LIMIT 1;
        IF name_ IS NOT NULL THEN
            RAISE EXCEPTION 'relationship "%" is the reference attribute "%"; set it on the entity instead', name_, name_
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object('kind', 'reference_relationship', 'field', name_)::text;
        END IF;
        RETURN NULL;
    END
    $function$;
    DROP TRIGGER IF EXISTS relationship_reference_guard ON relationship;
    CREATE TRIGGER relationship_reference_guard AFTER UPDATE OR DELETE ON relationship
      FOR EACH ROW EXECUTE FUNCTION relationship_reference_guard();
    CREATE TRIGGER relationship_reference_guard_added AFTER INSERT ON relationship
      REFERENCING NEW TABLE AS added FOR EACH STATEMENT EXECUTE FUNCTION relationship_reference_guard_added();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS relationship_reference_guard_added ON relationship;
    DROP FUNCTION IF EXISTS relationship_reference_guard_added();
    DROP TRIGGER IF EXISTS relationship_reference_guard ON relationship;
    CREATE TRIGGER relationship_reference_guard AFTER INSERT OR UPDATE OR DELETE ON relationship
      FOR EACH ROW EXECUTE FUNCTION relationship_reference_guard();
    DROP TRIGGER IF EXISTS entity_change_record_added ON entity;
    DROP FUNCTION IF EXISTS entity_change_record_added();
    DROP TRIGGER IF EXISTS entity_change_record ON entity;
    CREATE TRIGGER entity_change_record AFTER INSERT OR UPDATE OR DELETE ON entity
      FOR EACH ROW EXECUTE FUNCTION entity_change_record();
    DROP TRIGGER IF EXISTS relationship_validate_added ON relationship;
    DROP FUNCTION IF EXISTS relationship_validate_added();
    DROP TRIGGER IF EXISTS relationship_validate ON relationship;
    CREATE TRIGGER relationship_validate BEFORE INSERT OR UPDATE ON relationship
      FOR EACH ROW EXECUTE FUNCTION relationship_validate();
    """)
    for table, parents in HOT.items():
        args = ", ".join(f"'{p}:{c}:{t}'" for p, c, t in parents)
        op.execute(_trigger(table, "tenant_inherit", args))
        op.execute(f"DROP FUNCTION IF EXISTS tenant_inherit_{table}()")
