"""domain schema group A: entity_type, entity, attribute_definition,
entity_attribute, relationship_type, relationship

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS domain;

        CREATE TABLE domain.entity_type (
            id              UUID PRIMARY KEY,
            organization_id UUID REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            parent_type_id  UUID REFERENCES domain.entity_type(id),
            is_abstract     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, code)
        );

        CREATE TABLE domain.entity (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES iam.organization(id),
            entity_type_id  UUID NOT NULL REFERENCES domain.entity_type(id),
            code            VARCHAR(150),
            name            VARCHAR(255),
            description     TEXT,
            valid_from      TIMESTAMPTZ,
            valid_to        TIMESTAMPTZ,
            status          VARCHAR(50),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, entity_type_id, code)
        );

        CREATE TABLE domain.attribute_definition (
            id              UUID PRIMARY KEY,
            entity_type_id  UUID NOT NULL REFERENCES domain.entity_type(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            data_type       VARCHAR(50) NOT NULL,
            is_required     BOOLEAN NOT NULL DEFAULT FALSE,
            is_multi_value  BOOLEAN NOT NULL DEFAULT FALSE,
            default_value   JSONB,
            validation_rule JSONB,
            UNIQUE (entity_type_id, code)
        );

        CREATE TABLE domain.entity_attribute (
            id                  UUID PRIMARY KEY,
            entity_id           UUID NOT NULL REFERENCES domain.entity(id),
            attribute_id        UUID NOT NULL REFERENCES domain.attribute_definition(id),
            value_string        TEXT,
            value_number        NUMERIC,
            value_boolean       BOOLEAN,
            value_date          DATE,
            value_datetime      TIMESTAMPTZ,
            value_json          JSONB,
            UNIQUE (entity_id, attribute_id)
        );

        CREATE TABLE domain.relationship_type (
            id                  UUID PRIMARY KEY,
            code                VARCHAR(100) UNIQUE NOT NULL,
            name                VARCHAR(255) NOT NULL,
            source_entity_type  UUID REFERENCES domain.entity_type(id),
            target_entity_type  UUID REFERENCES domain.entity_type(id),
            cardinality         VARCHAR(30),
            is_directed         BOOLEAN NOT NULL DEFAULT TRUE,
            metadata            JSONB
        );

        CREATE TABLE domain.relationship (
            id                   UUID PRIMARY KEY,
            relationship_type_id UUID NOT NULL REFERENCES domain.relationship_type(id),
            source_entity_id     UUID NOT NULL REFERENCES domain.entity(id),
            target_entity_id     UUID NOT NULL REFERENCES domain.entity(id),
            valid_from           TIMESTAMPTZ,
            valid_to             TIMESTAMPTZ,
            attributes           JSONB,
            UNIQUE (relationship_type_id, source_entity_id, target_entity_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS domain.relationship;
        DROP TABLE IF EXISTS domain.relationship_type;
        DROP TABLE IF EXISTS domain.entity_attribute;
        DROP TABLE IF EXISTS domain.attribute_definition;
        DROP TABLE IF EXISTS domain.entity;
        DROP TABLE IF EXISTS domain.entity_type;
        """
    )
