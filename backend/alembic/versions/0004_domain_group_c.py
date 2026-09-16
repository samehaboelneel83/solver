"""domain schema group C: event_type, event, resource_type, resource,
time_calendar, time_period

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-16

"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.event_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT
        );

        CREATE TABLE domain.event (
            id              UUID PRIMARY KEY,
            event_type_id   UUID NOT NULL REFERENCES domain.event_type(id),
            entity_id       UUID REFERENCES domain.entity(id),
            occurred_at     TIMESTAMPTZ NOT NULL,
            data            JSONB
        );

        CREATE TABLE domain.resource_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            capacity_type   VARCHAR(50)
        );

        CREATE TABLE domain.resource (
            id                UUID PRIMARY KEY,
            resource_type_id UUID NOT NULL REFERENCES domain.resource_type(id),
            entity_id         UUID REFERENCES domain.entity(id),
            capacity          NUMERIC,
            unit              VARCHAR(50),
            availability_rule JSONB
        );

        CREATE TABLE domain.time_calendar (
            id              UUID PRIMARY KEY,
            organization_id UUID REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            timezone        VARCHAR(100)
        );

        CREATE TABLE domain.time_period (
            id              UUID PRIMARY KEY,
            calendar_id     UUID NOT NULL REFERENCES domain.time_calendar(id),
            parent_id       UUID REFERENCES domain.time_period(id),
            name            VARCHAR(255),
            start_time      TIMESTAMPTZ NOT NULL,
            end_time        TIMESTAMPTZ NOT NULL,
            level           INTEGER,
            metadata        JSONB
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS domain.time_period;
        DROP TABLE IF EXISTS domain.time_calendar;
        DROP TABLE IF EXISTS domain.resource;
        DROP TABLE IF EXISTS domain.resource_type;
        DROP TABLE IF EXISTS domain.event;
        DROP TABLE IF EXISTS domain.event_type;
        """
    )
