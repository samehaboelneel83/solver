"""0097: map data -- CAD drawings and other GIS sources stored as layers of features (DXF -> GIS).

- `gis_upload`   a file being imported: kept for a day while a person checks
                 its layers and where it lands, then imported or forgotten;
- `gis_dataset`  one imported drawing: its source, how it was placed on the
                 Earth (`placement`, app.gis.crs), its extent in WGS 84;
- `gis_layer`    the drawing's layers, with their CAD colour and counts;
- `gis_feature`  every feature: GeoJSON in WGS 84 (`geometry`), the drawing's
                 own coordinates (`source`, so a wrong CRS is corrected by
                 placing again, not by uploading again), its properties
                 (entity, colour, text, block, attributes) and its bounds.

**PostGIS when it is there.** If the server offers the `postgis` extension
it is created, and `gis_feature.geom` (geometry, SRID 4326) is kept from
`geometry` by a trigger, with a GiST index: spatial SQL, and QGIS or any
GIS desktop connecting to the database, see the features as a layer.
Without the extension (a plain postgres image) the tables are the same
less that column, and the platform works the same.

The setting `spatial.drawing_crs` names the EPSG code a domain's drawings
are usually in (0: ask each time); an import offers it first.
"""

import sqlalchemy as sa
from alembic import op

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None

_RLS = """
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON {t}
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO solver_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE gis_upload (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            filename        text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
            size_bytes      bigint NOT NULL,
            data            bytea NOT NULL,
            summary         jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX gis_upload_created_idx ON gis_upload (created_at);

        CREATE TABLE gis_dataset (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            domain_id       bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            source          jsonb NOT NULL DEFAULT '{}'::jsonb,
            placement       jsonb NOT NULL CHECK (jsonb_typeof(placement) = 'object'),
            bbox            double precision[] CHECK (bbox IS NULL OR cardinality(bbox) = 4),
            stats           jsonb NOT NULL DEFAULT '{}'::jsonb,
            notes           text[] NOT NULL DEFAULT '{}',
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX gis_dataset_domain_idx ON gis_dataset (domain_id);
        CREATE TRIGGER gis_dataset_set_updated_at BEFORE UPDATE ON gis_dataset
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER a_gis_dataset_tenant BEFORE INSERT OR UPDATE ON gis_dataset
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');

        CREATE TABLE gis_layer (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            dataset_id      bigint NOT NULL REFERENCES gis_dataset(id) ON DELETE CASCADE,
            name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 255),
            color           text NOT NULL DEFAULT '#1f2937' CHECK (color ~ '^#[0-9a-f]{6}$'),
            visible         boolean NOT NULL DEFAULT true,
            kinds           jsonb NOT NULL DEFAULT '{}'::jsonb,
            feature_count   integer NOT NULL DEFAULT 0,
            sort_order      integer NOT NULL DEFAULT 0,
            UNIQUE (dataset_id, name)
        );
        CREATE TRIGGER a_gis_layer_tenant BEFORE INSERT OR UPDATE ON gis_layer
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('gis_dataset:dataset_id:bigint');

        -- No tenant trigger on features: they are written in bulk by the import, with the
        -- dataset's organization; the policy's WITH CHECK still holds every row to it.
        CREATE TABLE gis_feature (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            dataset_id      bigint NOT NULL REFERENCES gis_dataset(id) ON DELETE CASCADE,
            layer_id        bigint NOT NULL REFERENCES gis_layer(id) ON DELETE CASCADE,
            kind            text NOT NULL CHECK (kind IN ('point', 'line', 'polygon', 'text')),
            geometry        jsonb NOT NULL CHECK (jsonb_typeof(geometry) = 'object'),
            source          jsonb,
            properties      jsonb NOT NULL DEFAULT '{}'::jsonb,
            minx double precision, miny double precision, maxx double precision, maxy double precision
        );
        CREATE INDEX gis_feature_layer_idx ON gis_feature (layer_id);
        CREATE INDEX gis_feature_dataset_idx ON gis_feature (dataset_id);
        """
    )
    for table in ("gis_upload", "gis_dataset", "gis_layer", "gis_feature"):
        op.execute(_RLS.format(t=table))
    op.execute(
        """
        GRANT USAGE, SELECT ON SEQUENCE gis_dataset_id_seq, gis_layer_id_seq, gis_feature_id_seq TO solver_app;
        DO $$
        BEGIN
            -- Available, and installed already or ours to install (creating it needs a superuser).
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'postgis')
               AND (EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')
                    OR (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)) THEN
                EXECUTE 'CREATE EXTENSION IF NOT EXISTS postgis';
                EXECUTE 'ALTER TABLE gis_feature ADD COLUMN geom geometry(Geometry, 4326)';
                EXECUTE 'CREATE INDEX gis_feature_geom_idx ON gis_feature USING gist (geom)';
                EXECUTE $f$
                    CREATE FUNCTION gis_feature_geom() RETURNS trigger LANGUAGE plpgsql AS $b$
                    BEGIN
                        NEW.geom := ST_SetSRID(ST_GeomFromGeoJSON(NEW.geometry::text), 4326);
                        RETURN NEW;
                    END $b$
                $f$;
                EXECUTE 'CREATE TRIGGER gis_feature_geom BEFORE INSERT OR UPDATE OF geometry ON gis_feature'
                        ' FOR EACH ROW EXECUTE FUNCTION gis_feature_geom()';
            END IF;
        END $$;
        """
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('spatial.drawing_crs', 'number', CAST('0' AS jsonb),"
            "         'The EPSG code CAD drawings in this domain are usually drawn in (0: ask on each import)')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'spatial.drawing_crs'")
    op.execute("DELETE FROM setting_key WHERE key = 'spatial.drawing_crs'")
    op.execute("DROP TABLE IF EXISTS gis_feature, gis_layer, gis_dataset, gis_upload")
    op.execute("DROP FUNCTION IF EXISTS gis_feature_geom()")
