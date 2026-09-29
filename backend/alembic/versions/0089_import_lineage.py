"""0089: validating an extraction against a mapping, and loading it (Epic UX, U-4).

An ingestion job (0085) ends with an artifact -- rows and a manifest -- that is
not yet domain data. `import_validation` is one check of that artifact against a
mapping (target entity type, source column -> target column): every row parsed
and written inside savepoints that are rolled back, so the report is the same
faults a load would meet, `{row, column, message}`. `import_load` is the load of
a validated mapping, and the lineage of the data it wrote: the artifact's
SHA-256 and the mapping's hash. One load per job and mapping: loading the same
artifact through the same mapping twice is refused.
"""

from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE import_validation (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            job_id           bigint NOT NULL REFERENCES ingestion_job(id) ON DELETE CASCADE,
            organization_id  uuid NOT NULL REFERENCES iam.organization(id),
            entity_type_id   bigint NOT NULL REFERENCES entity_type(id) ON DELETE CASCADE,
            mapping          jsonb NOT NULL,
            mapping_hash     text NOT NULL CHECK (mapping_hash ~ '^[0-9a-f]{64}$'),
            artifact_sha256  text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
            rows             integer NOT NULL CHECK (rows >= 0),
            ok               boolean NOT NULL,
            faults           jsonb NOT NULL DEFAULT '[]'::jsonb,
            validated_by     uuid REFERENCES iam.user_account(id),
            created_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX import_validation_job_idx ON import_validation (job_id);
        CREATE TRIGGER a_import_validation_tenant BEFORE INSERT ON import_validation
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('ingestion_job:job_id:bigint');
        ALTER TABLE import_validation ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON import_validation
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());

        CREATE TABLE import_load (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            job_id           bigint NOT NULL REFERENCES ingestion_job(id) ON DELETE CASCADE,
            validation_id    bigint NOT NULL REFERENCES import_validation(id) ON DELETE CASCADE,
            organization_id  uuid NOT NULL REFERENCES iam.organization(id),
            entity_type_id   bigint NOT NULL REFERENCES entity_type(id) ON DELETE CASCADE,
            mapping_hash     text NOT NULL,
            artifact_sha256  text NOT NULL,
            rows_written     integer NOT NULL CHECK (rows_written >= 0),
            loaded_by        uuid REFERENCES iam.user_account(id),
            created_at       timestamptz NOT NULL DEFAULT now(),
            UNIQUE (job_id, mapping_hash)
        );
        CREATE TRIGGER a_import_load_tenant BEFORE INSERT ON import_load
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('ingestion_job:job_id:bigint');
        ALTER TABLE import_load ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON import_load
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());

        -- Written by the API on a request; never changed after.
        GRANT SELECT, INSERT ON import_validation, import_load TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE import_validation_id_seq, import_load_id_seq TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS import_load; DROP TABLE IF EXISTS import_validation;")
