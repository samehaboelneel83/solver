"""0100: every change to a record kept -- who, when, and what each field was before and after.

The audit log (`iam.audit_event`) keeps hashes of administrative actions, for administrators. A
planner asking "who moved Truck 5, and where was it?" needs the values, on the record. This keeps
them in `entity_change`, written by a trigger on `entity` so every writer is covered -- the record
form, the grid, a workbook or file upload, a database import, a script -- and none can forget.

- `op`: insert, update or delete; an update that changes nothing but `updated_at` is not kept.
- `before` / `after`: the record's key, label, sort_order, active and attrs as they were and became.
- `actor`: the account that made the request, from the session setting `app.actor` that each request
  sets beside its tenant (`app.api.deps`); empty for system code (a migration, the seed).
- `entity_id` has no foreign key: a deleted record's history outlives it.

Tenant-scoped like every domain table: a row carries its record's organization.
"""
from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_change (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            entity_id       bigint NOT NULL,
            entity_type_id  bigint NOT NULL,
            at              timestamptz NOT NULL DEFAULT clock_timestamp(),
            actor           text,
            op              text NOT NULL CHECK (op IN ('insert', 'update', 'delete')),
            before          jsonb,
            after           jsonb
        );
        CREATE INDEX entity_change_entity_idx ON entity_change (entity_id, at DESC);
        ALTER TABLE entity_change ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON entity_change
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT ON entity_change TO solver_app;

        CREATE FUNCTION entity_snapshot(e entity) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
            SELECT jsonb_build_object('key', e.key, 'label', e.label, 'sort_order', e.sort_order,
                                      'active', e.active, 'attrs', e.attrs);
        $$;

        CREATE FUNCTION entity_change_record() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_actor text := nullif(current_setting('app.actor', true), '');
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO entity_change (organization_id, entity_id, entity_type_id, actor, op, before, after)
                VALUES (NEW.organization_id, NEW.id, NEW.entity_type_id, v_actor, 'insert', NULL, entity_snapshot(NEW));
            ELSIF TG_OP = 'UPDATE' THEN
                IF entity_snapshot(OLD) IS DISTINCT FROM entity_snapshot(NEW) THEN
                    INSERT INTO entity_change (organization_id, entity_id, entity_type_id, actor, op, before, after)
                    VALUES (NEW.organization_id, NEW.id, NEW.entity_type_id, v_actor, 'update',
                            entity_snapshot(OLD), entity_snapshot(NEW));
                END IF;
            ELSE
                INSERT INTO entity_change (organization_id, entity_id, entity_type_id, actor, op, before, after)
                VALUES (OLD.organization_id, OLD.id, OLD.entity_type_id, v_actor, 'delete', entity_snapshot(OLD), NULL);
            END IF;
            RETURN NULL;
        END $$;

        CREATE TRIGGER entity_change_record AFTER INSERT OR UPDATE OR DELETE ON entity
            FOR EACH ROW EXECUTE FUNCTION entity_change_record();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entity_change_record ON entity")
    op.execute("DROP FUNCTION IF EXISTS entity_change_record()")
    op.execute("DROP FUNCTION IF EXISTS entity_snapshot(entity)")
    op.execute("DROP TABLE IF EXISTS entity_change")
