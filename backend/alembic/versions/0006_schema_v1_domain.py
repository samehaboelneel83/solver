"""schema v1 DOMAIN half: domain, entity_type, attribute_def, entity,
relationship_type, relationship, parameter_def, parameter_value

Drops the v0 `domain` and `problem` schemas wholesale and creates the eight
v1 DOMAIN tables in `public`, together with the enums `entity_role` and
`attr_type`, the validation triggers and the `entity_descendants` helper.

The DDL is taken from `docs/schema/2026-09-18-schema-v1.sql` with the
amendments the design spec (§3) calls for, plus amendment (d) below:

  (a) every RAISE EXCEPTION in `entity_validate`, `relationship_validate`
      and `parameter_value_validate` carries ERRCODE '23514' (check_violation)
      and a JSON DETAIL payload, so the API can map it to a 422 naming the
      offending field instead of a generic 500. The payload shape is a
      contract with the API layer:
          {"kind": ..., "field": ..., "record": ..., "expected": ...}
      `kind` is one of unknown_attribute | required_attribute |
      attribute_type | type_mismatch | cardinality | cycle |
      parameter_index. `field` is the attribute or column at fault, or the
      relationship type's name for type_mismatch/cardinality/cycle.

  (c) `relationship_validate`'s recursive cycle walk excludes the row being
      validated (`id IS DISTINCT FROM NEW.id`) from both terms, so an UPDATE
      that re-points an existing hierarchy edge is not rejected by its own
      pre-update version still sitting in the table.

  (d) `parameter_value_cleanup` deletes with `entity_ids @> ARRAY[OLD.id]`
      instead of the supplied DDL's `OLD.id = ANY (entity_ids)`. NOT in the
      design spec -- this is a fourth amendment, added in fix round 1 after
      review. The two predicates are semantically identical for this
      DELETE, but only `@>` is an indexable operator for GIN `array_ops`:
      `= ANY (<array column>)` has no GIN strategy at all, so the
      `parameter_value_entities_gin` index created two lines below it had
      no possible user and every fired trigger scanned the whole table.
      Measured with EXPLAIN on 365 000 cells: `= ANY` planned a parallel
      seq scan (3763 buffers, 16.1 ms) and would not use the index even
      with `enable_seqscan = off`; `@>` plans a Bitmap Index Scan on
      `parameter_value_entities_gin` (262 buffers, 1.7 ms). The trigger is
      FOR EACH ROW on `entity` DELETE, so deleting a 365-entity type
      multiplies the difference by 365.

      Equivalence: for a non-NULL scalar `x`, `x = ANY (a)` and
      `a @> ARRAY[x]` select exactly the same rows. They differ only in
      how a NULL *element* of `a` is treated -- `= ANY` yields NULL where
      `@>` yields false -- and a DELETE keeps a row in neither case.
      `OLD.id` is the deleted entity's identity column and can never be
      NULL.

The `iam` schema is untouched.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-19

"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The v0 schemas go in their entirety. Spec §8: this is a destructive
    # migration by design -- there is no field data worth migrating, and no
    # mapping from the 31-table shape onto the 16-table one.
    op.execute("DROP SCHEMA IF EXISTS domain CASCADE")
    op.execute("DROP SCHEMA IF EXISTS problem CASCADE")

    op.execute(
        """
        CREATE TABLE domain (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name        text NOT NULL UNIQUE,
            created_at  timestamptz NOT NULL DEFAULT now()
        );

        -- role tells the compiler/UI how to treat a type (time-like, resource-like...)
        CREATE TYPE entity_role AS ENUM
            ('agent', 'resource', 'time', 'location', 'task', 'org', 'other');

        CREATE TABLE entity_type (
            id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id  bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
            name       text   NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$'),
            role       entity_role NOT NULL DEFAULT 'other',
            UNIQUE (domain_id, name)
        );

        CREATE TYPE attr_type AS ENUM
            ('integer', 'number', 'text', 'boolean', 'enum', 'time', 'date');

        CREATE TABLE attribute_def (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_type_id  bigint NOT NULL REFERENCES entity_type ON DELETE CASCADE,
            name            text   NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$' AND name <> 'id'),
            data_type       attr_type NOT NULL,
            required        boolean NOT NULL DEFAULT false,
            unit            text,
            enum_values     text[],
            default_value   jsonb,
            UNIQUE (entity_type_id, name),
            CHECK ((data_type = 'enum') = (enum_values IS NOT NULL))
        );

        CREATE TABLE entity (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_type_id  bigint NOT NULL REFERENCES entity_type ON DELETE CASCADE,
            key             text   NOT NULL,
            label           text,
            sort_order      int    NOT NULL DEFAULT 0,
            active          boolean NOT NULL DEFAULT true,
            attrs           jsonb  NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(attrs) = 'object'),
            UNIQUE (entity_type_id, key)
        );
        CREATE INDEX entity_attrs_gin ON entity USING gin (attrs);
        """
    )

    # attrs is JSONB (not EAV) but is validated against attribute_def on write.
    # Amendment (a): structured, machine-readable errors.
    op.execute(
        """
        CREATE FUNCTION entity_validate() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE d attribute_def; v jsonb; k text; ok boolean;
        BEGIN
            FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP
                IF NOT EXISTS (SELECT 1 FROM attribute_def
                               WHERE entity_type_id = NEW.entity_type_id AND name = k) THEN
                    RAISE EXCEPTION 'entity %: unknown attribute "%"', NEW.key, k
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object(
                                  'kind',   'unknown_attribute',
                                  'field',  k,
                                  'record', NEW.key)::text;
                END IF;
            END LOOP;
            FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = NEW.entity_type_id LOOP
                v := NEW.attrs -> d.name;
                IF v IS NULL AND d.default_value IS NOT NULL THEN
                    NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);
                    v := d.default_value;
                END IF;
                IF v IS NULL OR v = 'null' THEN
                    IF d.required THEN
                        RAISE EXCEPTION 'entity %: attribute "%" is required', NEW.key, d.name
                            USING ERRCODE = '23514',
                                  DETAIL  = jsonb_build_object(
                                      'kind',   'required_attribute',
                                      'field',  d.name,
                                      'record', NEW.key)::text;
                    END IF;
                    CONTINUE;
                END IF;
                ok := CASE d.data_type
                    WHEN 'integer' THEN jsonb_typeof(v) = 'number' AND (v #>> '{}')::numeric % 1 = 0
                    WHEN 'number'  THEN jsonb_typeof(v) = 'number'
                    WHEN 'boolean' THEN jsonb_typeof(v) = 'boolean'
                    WHEN 'enum'    THEN jsonb_typeof(v) = 'string' AND (v #>> '{}') = ANY (d.enum_values)
                    ELSE                jsonb_typeof(v) = 'string'
                END;
                IF NOT ok THEN
                    RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object(
                                  'kind',     'attribute_type',
                                  'field',    d.name,
                                  'record',   NEW.key,
                                  'expected', d.data_type::text)::text;
                END IF;
            END LOOP;
            RETURN NEW;
        END $$;

        CREATE TRIGGER entity_validate BEFORE INSERT OR UPDATE ON entity
            FOR EACH ROW EXECUTE FUNCTION entity_validate();
        """
    )

    op.execute(
        """
        -- Relationships. A hierarchy is a relationship_type with is_hierarchy = true,
        -- read as: from_entity is the PARENT of to_entity.
        CREATE TABLE relationship_type (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id     bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
            name          text   NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$'),
            from_type_id  bigint NOT NULL REFERENCES entity_type ON DELETE CASCADE,
            to_type_id    bigint NOT NULL REFERENCES entity_type ON DELETE CASCADE,
            cardinality   text   NOT NULL DEFAULT 'many_to_many'
                          CHECK (cardinality IN
                                 ('one_to_one', 'one_to_many', 'many_to_one', 'many_to_many')),
            is_hierarchy  boolean NOT NULL DEFAULT false,
            UNIQUE (domain_id, name),
            CHECK (NOT is_hierarchy OR (from_type_id = to_type_id AND cardinality = 'one_to_many'))
        );

        CREATE TABLE relationship (
            id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            relationship_type_id  bigint NOT NULL REFERENCES relationship_type ON DELETE CASCADE,
            from_entity_id        bigint NOT NULL REFERENCES entity ON DELETE CASCADE,
            to_entity_id          bigint NOT NULL REFERENCES entity ON DELETE CASCADE,
            attrs                 jsonb  NOT NULL DEFAULT '{}',
            valid_from            date,
            valid_to              date,
            UNIQUE (relationship_type_id, from_entity_id, to_entity_id),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
        );
        CREATE INDEX relationship_to_idx ON relationship (relationship_type_id, to_entity_id);
        """
    )

    # Amendment (a): structured errors, `field` = the relationship type's name.
    # Amendment (c): the row under validation is excluded from both terms of
    # the recursive walk, so re-pointing an existing edge is not flagged as a
    # cycle by its own pre-update version.
    op.execute(
        """
        CREATE FUNCTION relationship_validate() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE rt relationship_type;
        BEGIN
            SELECT * INTO rt FROM relationship_type WHERE id = NEW.relationship_type_id;
            IF (SELECT entity_type_id FROM entity WHERE id = NEW.from_entity_id) <> rt.from_type_id
            OR (SELECT entity_type_id FROM entity WHERE id = NEW.to_entity_id)   <> rt.to_type_id THEN
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
            IF rt.is_hierarchy AND (NEW.from_entity_id = NEW.to_entity_id OR EXISTS (
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
                RAISE EXCEPTION 'relationship "%": would create a cycle', rt.name
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object(
                              'kind',           'cycle',
                              'field',          rt.name,
                              'from_entity_id', NEW.from_entity_id,
                              'to_entity_id',   NEW.to_entity_id)::text;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER relationship_validate BEFORE INSERT OR UPDATE ON relationship
            FOR EACH ROW EXECUTE FUNCTION relationship_validate();
        """
    )

    op.execute(
        """
        -- node + everything beneath it (what `unit.descendants` in the IR will call)
        CREATE FUNCTION entity_descendants(p_entity bigint, p_rel_type bigint)
        RETURNS TABLE (entity_id bigint, depth int) LANGUAGE sql STABLE AS $$
            WITH RECURSIVE tree AS (
                SELECT p_entity AS entity_id, 0 AS depth
                UNION ALL
                SELECT r.to_entity_id, t.depth + 1
                  FROM relationship r JOIN tree t ON r.from_entity_id = t.entity_id
                 WHERE r.relationship_type_id = p_rel_type)
            SELECT * FROM tree
        $$;
        """
    )

    op.execute(
        """
        -- Indexed data that belongs to no single entity: demand[day, shift, location]
        CREATE TABLE parameter_def (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id       bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
            name            text   NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$'),
            index_type_ids  bigint[] NOT NULL CHECK (cardinality(index_type_ids) >= 1),
            default_value   int    NOT NULL DEFAULT 0,
            unit            text,
            UNIQUE (domain_id, name)
        );

        CREATE TABLE parameter_value (
            parameter_def_id  bigint   NOT NULL REFERENCES parameter_def ON DELETE CASCADE,
            entity_ids        bigint[] NOT NULL,
            value             int      NOT NULL,
            PRIMARY KEY (parameter_def_id, entity_ids)
        );
        """
    )

    # arrays cannot carry foreign keys, so validate them here.
    # Amendment (a): `field` is the offending column, `entity_ids`.
    op.execute(
        """
        CREATE FUNCTION parameter_value_validate() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE want bigint[]; got bigint[];
        BEGIN
            SELECT index_type_ids INTO want FROM parameter_def WHERE id = NEW.parameter_def_id;
            SELECT array_agg(e.entity_type_id ORDER BY u.ord) INTO got
              FROM unnest(NEW.entity_ids) WITH ORDINALITY u(id, ord) JOIN entity e ON e.id = u.id;
            IF got IS DISTINCT FROM want THEN
                RAISE EXCEPTION
                    'parameter_value: index % does not match parameter index types', NEW.entity_ids
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object(
                              'kind',     'parameter_index',
                              'field',    'entity_ids',
                              'record',   NEW.entity_ids,
                              'expected', want)::text;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER parameter_value_validate BEFORE INSERT OR UPDATE ON parameter_value
            FOR EACH ROW EXECUTE FUNCTION parameter_value_validate();

        -- Amendment (d): `entity_ids @> ARRAY[OLD.id]`, not
        -- `OLD.id = ANY (entity_ids)` -- see the module docstring.
        CREATE FUNCTION parameter_value_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM parameter_value WHERE entity_ids @> ARRAY[OLD.id];
            RETURN OLD;
        END $$;
        CREATE TRIGGER parameter_value_cleanup BEFORE DELETE ON entity
            FOR EACH ROW EXECUTE FUNCTION parameter_value_cleanup();
        CREATE INDEX parameter_value_entities_gin ON parameter_value USING gin (entity_ids);
        """
    )


def downgrade() -> None:
    # Destructive by design (spec §8). Downgrading drops the v1 DOMAIN tables
    # and their data; it does NOT recreate the v0 `domain`/`problem` schemas,
    # whose contents `upgrade()` destroyed. Data lost across 0006 is
    # unrecoverable -- restore from a database backup if you need it back.
    op.execute(
        """
        DROP TRIGGER IF EXISTS parameter_value_cleanup ON entity;
        DROP TRIGGER IF EXISTS parameter_value_validate ON parameter_value;
        DROP TRIGGER IF EXISTS relationship_validate ON relationship;
        DROP TRIGGER IF EXISTS entity_validate ON entity;

        DROP FUNCTION IF EXISTS parameter_value_cleanup();
        DROP FUNCTION IF EXISTS parameter_value_validate();
        DROP FUNCTION IF EXISTS entity_descendants(bigint, bigint);
        DROP FUNCTION IF EXISTS relationship_validate();
        DROP FUNCTION IF EXISTS entity_validate();

        DROP TABLE IF EXISTS parameter_value;
        DROP TABLE IF EXISTS parameter_def;
        DROP TABLE IF EXISTS relationship;
        DROP TABLE IF EXISTS relationship_type;
        DROP TABLE IF EXISTS entity;
        DROP TABLE IF EXISTS attribute_def;
        DROP TABLE IF EXISTS entity_type;
        DROP TABLE IF EXISTS domain;

        DROP TYPE IF EXISTS attr_type;
        DROP TYPE IF EXISTS entity_role;
        """
    )
