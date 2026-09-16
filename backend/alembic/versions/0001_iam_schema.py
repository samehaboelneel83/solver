"""iam schema: organization, user_account, role, user_role

Revision ID: 0001
Revises:
Create Date: 2026-09-16

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS iam;

        CREATE TABLE iam.organization (
            id              UUID PRIMARY KEY,
            parent_id       UUID REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (code)
        );

        CREATE TABLE iam.user_account (
            id              UUID PRIMARY KEY,
            organization_id UUID REFERENCES iam.organization(id),
            username        VARCHAR(150) UNIQUE NOT NULL,
            display_name    VARCHAR(255),
            email           VARCHAR(255),
            hashed_password VARCHAR(255) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE iam.role (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL
        );

        CREATE TABLE iam.user_role (
            id      UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES iam.user_account(id),
            role_id UUID NOT NULL REFERENCES iam.role(id),
            UNIQUE (user_id, role_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS iam.user_role;
        DROP TABLE IF EXISTS iam.role;
        DROP TABLE IF EXISTS iam.user_account;
        DROP TABLE IF EXISTS iam.organization;
        DROP SCHEMA IF EXISTS iam;
        """
    )
