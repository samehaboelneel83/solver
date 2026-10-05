"""0110: the record and link checks, quick on the common case.

A layout plan builds tens of thousands of records and a hundred thousand links (the camp-bed test,
October 2026: 35,000 records and 109,000 links took 112 s, and a bigger one passed the five-minute limit
of a build). EXPLAIN ANALYZE put nearly all of it in two per-row checks:

- `entity_reference_sync` (0.45 ms a record) turned a setting on and off for every record, even of a
  kind with no reference field. Now it returns at once when the kind has none (and no key was renamed).
- `relationship_validate` (0.3 ms a link) asked the type lineage twice per link even when the record's
  kind is exactly the end's kind. Now that case is compared directly, and the reference-field lookup is
  made only when the link could nest.

The same checks, the same errors; only the order of the work changes.
"""

from alembic import op

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE OR REPLACE FUNCTION entity_reference_sync() RETURNS trigger LANGUAGE plpgsql AS $function$
    -- The attribute is the record; the relationship is its mirror, so `via`, edge reads and the
    -- relationship checks apply. Written with solver.reference_sync on, which the guard allows.
    DECLARE d attribute_def; target bigint; r record; lineage bigint[];
    BEGIN
        lineage := entity_type_lineage(NEW.entity_type_id);
        IF NOT EXISTS (SELECT 1 FROM attribute_def WHERE entity_type_id = ANY (lineage) AND data_type::text = 'reference')
           AND NOT (TG_OP = 'UPDATE' AND OLD.key IS DISTINCT FROM NEW.key) THEN
            RETURN NULL;  -- nothing to mirror (0110: most records)
        END IF;
        PERFORM set_config('solver.reference_sync', 'on', true);
        FOR d IN SELECT * FROM attribute_def
                  WHERE entity_type_id = ANY (lineage)
                    AND data_type::text = 'reference' LOOP
            DELETE FROM relationship WHERE relationship_type_id = d.references_id AND from_entity_id = NEW.id;
            IF NEW.attrs ? d.name AND NEW.attrs -> d.name <> 'null' THEN
                SELECT e.id INTO target FROM entity e JOIN relationship_type rt ON rt.id = d.references_id
                 WHERE e.key = NEW.attrs ->> d.name AND entity_type_is_a(e.entity_type_id, rt.to_type_id)
                 LIMIT 1;
                INSERT INTO relationship (relationship_type_id, from_entity_id, to_entity_id)
                VALUES (d.references_id, NEW.id, target);
            END IF;
        END LOOP;
        -- A renamed target: whoever refers to it now names the new key.
        IF TG_OP = 'UPDATE' AND OLD.key IS DISTINCT FROM NEW.key THEN
            FOR r IN SELECT rel.from_entity_id AS source, ad.name AS attribute
                       FROM relationship rel JOIN attribute_def ad ON ad.references_id = rel.relationship_type_id
                      WHERE rel.to_entity_id = NEW.id LOOP
                UPDATE entity SET attrs = jsonb_set(attrs, ARRAY[r.attribute], to_jsonb(NEW.key))
                 WHERE id = r.source;
            END LOOP;
        END IF;
        PERFORM set_config('solver.reference_sync', 'off', true);
        RETURN NULL;
    END $function$;

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
        -- mirror between kinds that inherit from each other.
        v_nested := rt.is_hierarchy;
        IF NOT v_nested AND (rt.from_type_id = rt.to_type_id OR entity_type_is_a(rt.from_type_id, rt.to_type_id)
                             OR entity_type_is_a(rt.to_type_id, rt.from_type_id)) THEN
            SELECT ad.name INTO v_attr FROM attribute_def ad WHERE ad.references_id = rt.id;
            v_nested := v_attr IS NOT NULL;
        ELSIF v_nested THEN
            SELECT ad.name INTO v_attr FROM attribute_def ad WHERE ad.references_id = rt.id;
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
    END $function$;
    """)


def downgrade() -> None:
    pass  # the same checks as 0098/0067's, only quicker: nothing to undo
