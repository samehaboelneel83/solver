-- Problem-Solving Platform: schema v1  (PostgreSQL 14+)
--
--   DOMAIN   domain, entity_type, attribute_def, entity,
--            relationship_type, relationship, parameter_def, parameter_value
--   PROBLEM  template, problem, model_version (immutable IR), scenario
--   RUN      dataset (immutable snapshot), run, solution, constraint_result
--
-- Live domain data is editable. A run never reads it directly: it reads a
-- frozen dataset snapshot, so every run stays reproducible.

BEGIN;

-- ===========================================================================
-- DOMAIN MODEL
-- ===========================================================================

CREATE TABLE domain (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- role tells the compiler/UI how to treat a type (time-like, resource-like...)
CREATE TYPE entity_role AS ENUM ('agent', 'resource', 'time', 'location', 'task', 'org', 'other');

CREATE TABLE entity_type (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id  bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
    name       text   NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$'),  -- used in IR expressions
    role       entity_role NOT NULL DEFAULT 'other',
    UNIQUE (domain_id, name)
);

CREATE TYPE attr_type AS ENUM ('integer', 'number', 'text', 'boolean', 'enum', 'time', 'date');

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
    key             text   NOT NULL,              -- stable human id: 'ahmed', 'mon'
    label           text,
    sort_order      int    NOT NULL DEFAULT 0,    -- mon..sun, morning..night
    active          boolean NOT NULL DEFAULT true,
    attrs           jsonb  NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(attrs) = 'object'),
    UNIQUE (entity_type_id, key)
);
CREATE INDEX entity_attrs_gin ON entity USING gin (attrs);

-- attrs is JSONB (not EAV) but is validated against attribute_def on write
CREATE FUNCTION entity_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d attribute_def; v jsonb; k text; ok boolean;
BEGIN
    FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP
        IF NOT EXISTS (SELECT 1 FROM attribute_def
                       WHERE entity_type_id = NEW.entity_type_id AND name = k) THEN
            RAISE EXCEPTION 'entity %: unknown attribute "%"', NEW.key, k;
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
                RAISE EXCEPTION 'entity %: attribute "%" is required', NEW.key, d.name;
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
            RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type;
        END IF;
    END LOOP;
    RETURN NEW;
END $$;

CREATE TRIGGER entity_validate BEFORE INSERT OR UPDATE ON entity
    FOR EACH ROW EXECUTE FUNCTION entity_validate();

-- Relationships. A hierarchy is a relationship_type with is_hierarchy = true,
-- read as: from_entity is the PARENT of to_entity.
CREATE TABLE relationship_type (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id     bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
    name          text   NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$'),
    from_type_id  bigint NOT NULL REFERENCES entity_type ON DELETE CASCADE,
    to_type_id    bigint NOT NULL REFERENCES entity_type ON DELETE CASCADE,
    cardinality   text   NOT NULL DEFAULT 'many_to_many'
                  CHECK (cardinality IN ('one_to_one', 'one_to_many', 'many_to_one', 'many_to_many')),
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

CREATE FUNCTION relationship_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rt relationship_type;
BEGIN
    SELECT * INTO rt FROM relationship_type WHERE id = NEW.relationship_type_id;
    IF (SELECT entity_type_id FROM entity WHERE id = NEW.from_entity_id) <> rt.from_type_id
    OR (SELECT entity_type_id FROM entity WHERE id = NEW.to_entity_id)   <> rt.to_type_id THEN
        RAISE EXCEPTION 'relationship "%": entity types do not match', rt.name;
    END IF;
    IF rt.cardinality IN ('one_to_many', 'one_to_one') AND EXISTS (
        SELECT 1 FROM relationship r WHERE r.relationship_type_id = rt.id
           AND r.to_entity_id = NEW.to_entity_id AND r.id IS DISTINCT FROM NEW.id) THEN
        RAISE EXCEPTION 'relationship "%": target already has a source', rt.name;
    END IF;
    IF rt.cardinality IN ('many_to_one', 'one_to_one') AND EXISTS (
        SELECT 1 FROM relationship r WHERE r.relationship_type_id = rt.id
           AND r.from_entity_id = NEW.from_entity_id AND r.id IS DISTINCT FROM NEW.id) THEN
        RAISE EXCEPTION 'relationship "%": source already has a target', rt.name;
    END IF;
    IF rt.is_hierarchy AND (NEW.from_entity_id = NEW.to_entity_id OR EXISTS (
        WITH RECURSIVE down AS (
            SELECT to_entity_id AS id FROM relationship
             WHERE relationship_type_id = rt.id AND from_entity_id = NEW.to_entity_id
            UNION
            SELECT r.to_entity_id FROM relationship r JOIN down ON r.from_entity_id = down.id
             WHERE r.relationship_type_id = rt.id)
        SELECT 1 FROM down WHERE id = NEW.from_entity_id)) THEN
        RAISE EXCEPTION 'relationship "%": would create a cycle', rt.name;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER relationship_validate BEFORE INSERT OR UPDATE ON relationship
    FOR EACH ROW EXECUTE FUNCTION relationship_validate();

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
    entity_ids        bigint[] NOT NULL,     -- same order as index_type_ids
    value             int      NOT NULL,
    PRIMARY KEY (parameter_def_id, entity_ids)
);

-- arrays cannot carry foreign keys, so validate them here
CREATE FUNCTION parameter_value_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE want bigint[]; got bigint[];
BEGIN
    SELECT index_type_ids INTO want FROM parameter_def WHERE id = NEW.parameter_def_id;
    SELECT array_agg(e.entity_type_id ORDER BY u.ord) INTO got
      FROM unnest(NEW.entity_ids) WITH ORDINALITY u(id, ord) JOIN entity e ON e.id = u.id;
    IF got IS DISTINCT FROM want THEN
        RAISE EXCEPTION 'parameter_value: index % does not match parameter index types', NEW.entity_ids;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER parameter_value_validate BEFORE INSERT OR UPDATE ON parameter_value
    FOR EACH ROW EXECUTE FUNCTION parameter_value_validate();

CREATE FUNCTION parameter_value_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM parameter_value WHERE OLD.id = ANY (entity_ids);
    RETURN OLD;
END $$;
CREATE TRIGGER parameter_value_cleanup BEFORE DELETE ON entity
    FOR EACH ROW EXECUTE FUNCTION parameter_value_cleanup();
CREATE INDEX parameter_value_entities_gin ON parameter_value USING gin (entity_ids);

-- ===========================================================================
-- PROBLEM MODEL
-- ===========================================================================

-- A template is seed data: the types/params to create plus a starting IR.
CREATE TABLE template (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text  NOT NULL UNIQUE,
    ir_version   text  NOT NULL,
    domain_seed  jsonb NOT NULL DEFAULT '{}',
    default_ir   jsonb NOT NULL
);

CREATE TABLE problem (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id    bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
    template_id  bigint REFERENCES template,
    name         text   NOT NULL,
    owner        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domain_id, name)
);

-- Immutable. Editing a model = inserting the next version.
CREATE TABLE model_version (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    problem_id  bigint NOT NULL REFERENCES problem ON DELETE CASCADE,
    version     int    NOT NULL,
    ir          jsonb  NOT NULL,
    ir_hash     text   NOT NULL,             -- set by trigger
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (problem_id, version)
);

-- What-if = a patch over one model version. Shape matches ProblemIR.patched():
--   {"disable": ["c_x"], "harden": ["c_y"], "soften": {"c_z": 100}}
CREATE TABLE scenario (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    problem_id        bigint NOT NULL REFERENCES problem ON DELETE CASCADE,
    model_version_id  bigint NOT NULL REFERENCES model_version,
    name              text   NOT NULL,
    patch             jsonb  NOT NULL DEFAULT '{}',
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (problem_id, name)
);

-- ===========================================================================
-- RUNS
-- ===========================================================================

-- Frozen copy of the domain data, in exactly the JSON shape psp/data.py reads.
CREATE TABLE dataset (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    problem_id  bigint NOT NULL REFERENCES problem ON DELETE CASCADE,
    data        jsonb  NOT NULL,
    data_hash   text   NOT NULL,             -- set by trigger
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (problem_id, data_hash)           -- identical snapshots are shared
);

CREATE TYPE run_status AS ENUM
    ('queued', 'running', 'optimal', 'feasible', 'infeasible', 'unknown', 'error');

CREATE TABLE run (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scenario_id       bigint NOT NULL REFERENCES scenario ON DELETE CASCADE,
    dataset_id        bigint NOT NULL REFERENCES dataset,
    status            run_status NOT NULL DEFAULT 'queued',
    solver            text NOT NULL DEFAULT 'cp-sat',
    solver_version    text,
    compiler_version  text,
    params            jsonb NOT NULL DEFAULT '{}',   -- time_limit, workers...
    seed              int   NOT NULL DEFAULT 1,
    objective         bigint,
    wall_time_s       double precision,
    conflict          jsonb,    -- infeasible: [{"constraint_id": "...", "instance": [...]}]
    conflict_minimal  boolean,
    error             text,
    queued_at         timestamptz NOT NULL DEFAULT now(),
    started_at        timestamptz,
    finished_at       timestamptz
);
CREATE INDEX run_scenario_idx ON run (scenario_id, queued_at DESC);
CREATE INDEX run_queue_idx    ON run (queued_at) WHERE status = 'queued';

CREATE TABLE solution (
    run_id       bigint PRIMARY KEY REFERENCES run ON DELETE CASCADE,
    assignments  jsonb NOT NULL                -- {"assign": [["ahmed","mon","morning","hq"], ...]}
);

-- Normalized on purpose: this is what you query ACROSS runs.
CREATE TABLE constraint_result (
    run_id           bigint  NOT NULL REFERENCES run ON DELETE CASCADE,
    constraint_id    text    NOT NULL,
    label            text    NOT NULL,
    hard             boolean NOT NULL,
    satisfied        boolean NOT NULL,
    total_violation  int     NOT NULL DEFAULT 0,
    penalty_paid     bigint  NOT NULL DEFAULT 0,
    violations       jsonb   NOT NULL DEFAULT '[]',  -- [{"instance": [...], "amount": 1}]
    PRIMARY KEY (run_id, constraint_id)
);
CREATE INDEX constraint_result_violated_idx ON constraint_result (constraint_id) WHERE NOT satisfied;

-- ---------------------------------------------------------------------------
-- hashing + immutability
-- ---------------------------------------------------------------------------
CREATE FUNCTION set_hash() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'model_version' THEN
        NEW.ir_hash := encode(sha256(convert_to(NEW.ir::text, 'UTF8')), 'hex');
    ELSE
        NEW.data_hash := encode(sha256(convert_to(NEW.data::text, 'UTF8')), 'hex');
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER model_version_hash BEFORE INSERT ON model_version FOR EACH ROW EXECUTE FUNCTION set_hash();
CREATE TRIGGER dataset_hash       BEFORE INSERT ON dataset       FOR EACH ROW EXECUTE FUNCTION set_hash();

CREATE FUNCTION forbid_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable; insert a new row instead', TG_TABLE_NAME;
END $$;
CREATE TRIGGER model_version_immutable     BEFORE UPDATE ON model_version     FOR EACH ROW EXECUTE FUNCTION forbid_update();
CREATE TRIGGER dataset_immutable           BEFORE UPDATE ON dataset           FOR EACH ROW EXECUTE FUNCTION forbid_update();
CREATE TRIGGER solution_immutable          BEFORE UPDATE ON solution          FOR EACH ROW EXECUTE FUNCTION forbid_update();
CREATE TRIGGER constraint_result_immutable BEFORE UPDATE ON constraint_result FOR EACH ROW EXECUTE FUNCTION forbid_update();

CREATE FUNCTION next_model_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.version IS NULL THEN
        SELECT coalesce(max(version), 0) + 1 INTO NEW.version
          FROM model_version WHERE problem_id = NEW.problem_id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER model_version_number BEFORE INSERT ON model_version FOR EACH ROW EXECUTE FUNCTION next_model_version();

-- ---------------------------------------------------------------------------
-- snapshot: live domain tables -> frozen dataset
-- ---------------------------------------------------------------------------
-- Reads the set and parameter names from the IR and resolves them against the
-- problem's domain. Returns an existing dataset id if nothing changed.
CREATE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
    v_problem bigint; v_domain bigint; v_ir jsonb;
    v_sets jsonb := '{}'; v_params jsonb := '{}';
    v_name text; v_rows jsonb; v_data jsonb; v_id bigint; v_hash text;
BEGIN
    SELECT mv.problem_id, p.domain_id, mv.ir INTO v_problem, v_domain, v_ir
      FROM model_version mv JOIN problem p ON p.id = mv.problem_id
     WHERE mv.id = p_model_version;
    IF NOT FOUND THEN RAISE EXCEPTION 'model_version % not found', p_model_version; END IF;

    FOR v_name IN SELECT jsonb_array_elements_text(v_ir -> 'sets') LOOP
        IF NOT EXISTS (SELECT 1 FROM entity_type WHERE domain_id = v_domain AND name = v_name) THEN
            RAISE EXCEPTION 'IR set "%" has no entity_type in this domain', v_name;
        END IF;
        SELECT coalesce(jsonb_agg(jsonb_build_object('id', e.key) || e.attrs
                                  ORDER BY e.sort_order, e.key), '[]')
          INTO v_rows
          FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
         WHERE t.domain_id = v_domain AND t.name = v_name AND e.active;
        v_sets := v_sets || jsonb_build_object(v_name, v_rows);
    END LOOP;

    FOR v_name IN SELECT jsonb_object_keys(coalesce(v_ir -> 'parameters', '{}')) LOOP
        IF NOT EXISTS (SELECT 1 FROM parameter_def WHERE domain_id = v_domain AND name = v_name) THEN
            RAISE EXCEPTION 'IR parameter "%" has no parameter_def in this domain', v_name;
        END IF;
        SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]') INTO v_rows FROM (
            SELECT jsonb_object_agg(t.name, e.key) || jsonb_build_object('value', pv.value) AS row_json
              FROM parameter_def pd
              JOIN parameter_value pv ON pv.parameter_def_id = pd.id
              CROSS JOIN LATERAL unnest(pv.entity_ids) AS u(eid)
              JOIN entity e ON e.id = u.eid
              JOIN entity_type t ON t.id = e.entity_type_id
             WHERE pd.domain_id = v_domain AND pd.name = v_name
             GROUP BY pv.parameter_def_id, pv.entity_ids, pv.value
            HAVING bool_and(e.active)) q;
        v_params := v_params || jsonb_build_object(v_name, v_rows);
    END LOOP;

    v_data := jsonb_build_object('sets', v_sets, 'parameters', v_params);
    v_hash := encode(sha256(convert_to(v_data::text, 'UTF8')), 'hex');
    SELECT id INTO v_id FROM dataset WHERE problem_id = v_problem AND data_hash = v_hash;
    IF v_id IS NULL THEN
        INSERT INTO dataset (problem_id, data) VALUES (v_problem, v_data) RETURNING id INTO v_id;
    END IF;
    RETURN v_id;
END $$;

-- ---------------------------------------------------------------------------
-- convenience views
-- ---------------------------------------------------------------------------
CREATE VIEW run_overview AS
SELECT r.id AS run_id, p.name AS problem, s.name AS scenario, mv.version AS model_version,
       r.dataset_id, r.status, r.objective, r.wall_time_s, r.finished_at,
       (SELECT count(*) FROM constraint_result c WHERE c.run_id = r.id AND NOT c.satisfied) AS violated,
       (SELECT coalesce(sum(penalty_paid), 0) FROM constraint_result c WHERE c.run_id = r.id) AS penalty
  FROM run r
  JOIN scenario s       ON s.id  = r.scenario_id
  JOIN model_version mv ON mv.id = s.model_version_id
  JOIN problem p        ON p.id  = s.problem_id;

-- NOTE (not in the original): the DDL as supplied opens with BEGIN; and ends
-- after the run_overview view without a COMMIT. Added here so the file runs
-- standalone. Remove if the original omission was deliberate.
COMMIT;
