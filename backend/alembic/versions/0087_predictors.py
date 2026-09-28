"""0087: predictors -- trained models as domain data (Epic ML).

A `predictor` is a trained regression model a problem reads through the IR's
`predict` term: a domain's own tree ensemble, stored as `tree-ensemble/1`
JSON (`app.ml.trees`) and never as a pickle, because loading a pickle runs
code and a model is data.

`snapshot_dataset()` now also freezes the predictors a model version
declares (the IR's optional `predictors` key), under a `predictors` key of
the dataset -- **and only when the IR declares any**. A model that declares
none produces byte-for-byte the dataset it produced before this migration,
so every stored `data_hash` still matches and nothing is re-solved (the
contract's widening rule, §10.1). The function body is 0068's with one
loop added; the downgrade restores 0068's exactly.
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def _snapshot_0068() -> str:
    """0068's `snapshot_dataset()`, read from that migration so the two can
    never disagree about what is being extended or restored."""
    path = Path(__file__).with_name("0068_entity_valued_parameters.py")
    spec = importlib.util.spec_from_file_location("m0068", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module._SNAPSHOT_DATASET


_DECLARE_ANCHOR = "v_rels jsonb := '{}';"
_DATA_ANCHOR = "            v_data := jsonb_build_object('labels', v_labels)"
_PREDICTORS_LOOP = """
            -- 0087: the predictors the model declares, frozen with the data.
            IF v_ir ? 'predictors' THEN
                FOR v_name IN SELECT jsonb_object_keys(coalesce(v_ir -> 'predictors', '{}')) LOOP
                    IF NOT EXISTS (SELECT 1 FROM predictor
                                   WHERE domain_id = v_domain AND name = v_name) THEN
                        RAISE EXCEPTION 'IR predictor "%" has no predictor in this domain', v_name;
                    END IF;
                    v_preds := v_preds || jsonb_build_object(v_name, (
                        SELECT jsonb_build_object('model', pr.model) FROM predictor pr
                         WHERE pr.domain_id = v_domain AND pr.name = v_name));
                END LOOP;
            END IF;

"""
_DATA_TAIL_OLD = """                                         'relationships', v_rels);"""
_DATA_TAIL_NEW = """                                         'relationships', v_rels)
                      || CASE WHEN v_ir ? 'predictors'
                              THEN jsonb_build_object('predictors', v_preds)
                              ELSE '{}'::jsonb END;"""


def _snapshot_0087() -> str:
    body = _snapshot_0068()
    for anchor in (_DECLARE_ANCHOR, _DATA_ANCHOR, _DATA_TAIL_OLD):
        assert body.count(anchor) == 1, f"0068's snapshot_dataset() changed near {anchor!r}"
    body = body.replace(_DECLARE_ANCHOR, _DECLARE_ANCHOR + " v_preds jsonb := '{}';")
    body = body.replace(_DATA_ANCHOR, _PREDICTORS_LOOP + _DATA_ANCHOR)
    return body.replace(_DATA_TAIL_OLD, _DATA_TAIL_NEW)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE predictor (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            domain_id       bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            name            text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$' AND length(name) <= 63),
            note            text CHECK (note IS NULL OR length(note) <= 2000),
            inputs          text[] NOT NULL CHECK (cardinality(inputs) BETWEEN 1 AND 32),
            model           jsonb NOT NULL CHECK (jsonb_typeof(model) = 'object'
                                                  AND model ->> 'format' = 'tree-ensemble/1'),
            metrics         jsonb NOT NULL DEFAULT '{}'::jsonb,
            training        jsonb,
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (domain_id, name)
        );
        CREATE INDEX predictor_organization_idx ON predictor (organization_id);
        CREATE TRIGGER predictor_set_updated_at BEFORE UPDATE ON predictor
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER a_predictor_tenant BEFORE INSERT OR UPDATE ON predictor
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE predictor ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON predictor
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON predictor TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE predictor_id_seq TO solver_app;
        """
    )
    op.execute(_snapshot_0087())


def downgrade() -> None:
    op.execute(_snapshot_0068())
    op.execute("DROP TABLE IF EXISTS predictor")
