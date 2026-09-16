"""problem schema: problem, scenario, variable_definition,
variable_dimension, constraint_definition, constraint_scope, objective,
objective_component, parameter

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-16

"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS problem;

        CREATE TABLE problem.problem (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            problem_type    VARCHAR(100),
            version         INTEGER NOT NULL DEFAULT 1,
            status          VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
            created_by      UUID REFERENCES iam.user_account(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, code, version)
        );

        CREATE TABLE problem.scenario (
            id                  UUID PRIMARY KEY,
            problem_id          UUID NOT NULL REFERENCES problem.problem(id),
            code                VARCHAR(100) NOT NULL,
            name                VARCHAR(255) NOT NULL,
            description         TEXT,
            parent_scenario_id  UUID REFERENCES problem.scenario(id),
            parameters          JSONB,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.variable_definition (
            id                UUID PRIMARY KEY,
            problem_id        UUID NOT NULL REFERENCES problem.problem(id),
            code              VARCHAR(150) NOT NULL,
            name              VARCHAR(255) NOT NULL,
            variable_type     VARCHAR(50) NOT NULL,
            description       TEXT,
            domain_definition JSONB,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.variable_dimension (
            id              UUID PRIMARY KEY,
            variable_id     UUID NOT NULL REFERENCES problem.variable_definition(id),
            dimension_order INTEGER NOT NULL,
            dimension_type  VARCHAR(50) NOT NULL,
            domain_source   JSONB
        );

        CREATE TABLE problem.constraint_definition (
            id              UUID PRIMARY KEY,
            problem_id      UUID NOT NULL REFERENCES problem.problem(id),
            code            VARCHAR(150) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            constraint_type VARCHAR(100),
            expression      JSONB,
            severity        VARCHAR(30),
            is_hard         BOOLEAN NOT NULL DEFAULT TRUE,
            weight          NUMERIC,
            priority        INTEGER,
            description     TEXT,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.constraint_scope (
            id                 UUID PRIMARY KEY,
            constraint_id      UUID NOT NULL REFERENCES problem.constraint_definition(id),
            hierarchy_id       UUID REFERENCES domain.hierarchy(id),
            hierarchy_node_id  UUID REFERENCES domain.hierarchy_node(id),
            entity_id          UUID REFERENCES domain.entity(id),
            scope_type         VARCHAR(50),
            parameters         JSONB
        );

        CREATE TABLE problem.objective (
            id              UUID PRIMARY KEY,
            problem_id      UUID NOT NULL REFERENCES problem.problem(id),
            code            VARCHAR(150) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            objective_type  VARCHAR(30) NOT NULL,
            expression      JSONB,
            priority        INTEGER,
            weight          NUMERIC,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.objective_component (
            id              UUID PRIMARY KEY,
            objective_id    UUID NOT NULL REFERENCES problem.objective(id),
            code            VARCHAR(150),
            expression      JSONB,
            weight          NUMERIC,
            priority        INTEGER
        );

        CREATE TABLE problem.parameter (
            id              UUID PRIMARY KEY,
            problem_id      UUID NOT NULL REFERENCES problem.problem(id),
            code            VARCHAR(150) NOT NULL,
            name            VARCHAR(255),
            data_type       VARCHAR(50),
            value           JSONB,
            is_runtime      BOOLEAN DEFAULT FALSE,
            UNIQUE (problem_id, code)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS problem.parameter;
        DROP TABLE IF EXISTS problem.objective_component;
        DROP TABLE IF EXISTS problem.objective;
        DROP TABLE IF EXISTS problem.constraint_scope;
        DROP TABLE IF EXISTS problem.constraint_definition;
        DROP TABLE IF EXISTS problem.variable_dimension;
        DROP TABLE IF EXISTS problem.variable_definition;
        DROP TABLE IF EXISTS problem.scenario;
        DROP TABLE IF EXISTS problem.problem;
        DROP SCHEMA IF EXISTS problem;
        """
    )
