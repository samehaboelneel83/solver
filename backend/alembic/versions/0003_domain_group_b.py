"""domain schema group B: hierarchy, hierarchy_node, role_type,
entity_role, state_type, entity_state

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16

"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.hierarchy (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            entity_type_id  UUID REFERENCES domain.entity_type(id),
            description     TEXT
        );

        CREATE TABLE domain.hierarchy_node (
            id              UUID PRIMARY KEY,
            hierarchy_id    UUID NOT NULL REFERENCES domain.hierarchy(id),
            entity_id       UUID NOT NULL REFERENCES domain.entity(id),
            parent_node_id  UUID REFERENCES domain.hierarchy_node(id),
            level           INTEGER NOT NULL,
            sort_order      INTEGER,
            UNIQUE (hierarchy_id, entity_id)
        );

        CREATE TABLE domain.role_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT
        );

        CREATE TABLE domain.entity_role (
            id              UUID PRIMARY KEY,
            entity_id       UUID NOT NULL REFERENCES domain.entity(id),
            role_type_id    UUID NOT NULL REFERENCES domain.role_type(id),
            valid_from      TIMESTAMPTZ,
            valid_to        TIMESTAMPTZ,
            attributes      JSONB
        );

        CREATE TABLE domain.state_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            entity_type_id  UUID REFERENCES domain.entity_type(id)
        );

        CREATE TABLE domain.entity_state (
            id              UUID PRIMARY KEY,
            entity_id       UUID NOT NULL REFERENCES domain.entity(id),
            state_type_id   UUID NOT NULL REFERENCES domain.state_type(id),
            state_value     VARCHAR(100) NOT NULL,
            valid_from      TIMESTAMPTZ NOT NULL,
            valid_to        TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS domain.entity_state;
        DROP TABLE IF EXISTS domain.state_type;
        DROP TABLE IF EXISTS domain.entity_role;
        DROP TABLE IF EXISTS domain.role_type;
        DROP TABLE IF EXISTS domain.hierarchy_node;
        DROP TABLE IF EXISTS domain.hierarchy;
        """
    )
