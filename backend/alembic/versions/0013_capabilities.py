"""0013: capabilities, so a role means something.

Today `iam.role` holds zero rows, `iam.user_role` holds zero rows, and every
authenticated user can do everything: publish a model, edit a domain, submit a
run, choose a solver. The roadmap's Phase 5 calls this "nominal", which is
generous -- a permission model nobody enforces is a permission model that is
wrong in exactly one direction.

**Capabilities are rows, not an enum.** A new capability is an INSERT, not a
migration, which is the same decision the expression catalogue and the solver
registry took: the vocabulary is data. But it is a *referenced* table, so a
typo in a grant is a foreign-key violation rather than a permission that
silently grants nothing -- the failure mode an enum would also catch and a
plain text column would not.

**Four roles, seeded.** They are a starting vocabulary, not a fixed one:

    admin      everything, including granting
    modeller   shape the domain and publish models; may solve
    planner    solve and read; may not change the model
    viewer     read only

The split that matters is `modeller` from `planner`. A planner asking "what if
Thursday needed one more?" must be able to run a scenario without being able
to change the model everyone else's answers depend on.

**The existing admin keeps working.** Every user who exists when this runs is
granted `admin`, because the alternative is a migration that locks the only
account out of its own platform. That is a deliberate, recorded choice: this
migration introduces enforcement without changing who can do what today, and
narrowing comes after, by revoking.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


# The starting vocabulary. Each row is a thing the API checks for by name;
# `group` exists so a UI can present them without hardcoding a grouping.
_CAPABILITIES = [
    ("domain.edit", "domain", "Add, change and remove entity types, entities, relationships and parameters"),
    ("model.publish", "model", "Publish a new model version, and create scenarios"),
    ("run.submit", "run", "Solve a scenario and read the answer"),
    ("solver.configure", "run", "Choose which solver runs, rather than letting the platform choose"),
    ("iam.manage", "iam", "Grant and revoke roles"),
]

_ROLES = {
    "admin": [c[0] for c in _CAPABILITIES],
    "modeller": ["domain.edit", "model.publish", "run.submit", "solver.configure"],
    "planner": ["run.submit"],
    "viewer": [],
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iam.capability (
            code        varchar(100) PRIMARY KEY,
            "group"     varchar(50)  NOT NULL,
            description text         NOT NULL
        );

        -- The grant itself. ON DELETE CASCADE on both sides: deleting a role
        -- must not leave grants pointing at nothing, and a capability that is
        -- retired takes its grants with it.
        CREATE TABLE iam.role_capability (
            role_id         uuid         NOT NULL REFERENCES iam.role(id) ON DELETE CASCADE,
            capability_code varchar(100) NOT NULL REFERENCES iam.capability(code) ON DELETE CASCADE,
            PRIMARY KEY (role_id, capability_code)
        );
        CREATE INDEX role_capability_by_capability ON iam.role_capability (capability_code);
        """
    )

    bind = op.get_bind()
    # Bound, not interpolated: a description with an apostrophe in it would
    # otherwise break the migration, and a migration is the one place a
    # syntax error is most expensive.
    bind.execute(
        sa.text(
            'INSERT INTO iam.capability (code, "group", description)'
            " VALUES (:code, :grp, :description)"
        ),
        [{"code": c, "grp": g, "description": d} for c, g, d in _CAPABILITIES],
    )

    for role, capabilities in _ROLES.items():
        bind.execute(
            sa.text(
                "INSERT INTO iam.role (id, code, name)"
                " VALUES (gen_random_uuid(), :code, :name)"
                " ON CONFLICT (code) DO NOTHING"
            ),
            {"code": role, "name": role.title()},
        )
        if capabilities:
            bind.execute(
                sa.text(
                    "INSERT INTO iam.role_capability (role_id, capability_code)"
                    " SELECT id, :capability FROM iam.role WHERE code = :role"
                ),
                [{"capability": c, "role": role} for c in capabilities],
            )

    # Everyone who already exists becomes an admin. Enforcement arrives with
    # this migration; narrowing is a later, deliberate act of revoking, not a
    # side effect of turning the lights on.
    op.execute(
        """
        INSERT INTO iam.user_role (id, user_id, role_id)
        SELECT gen_random_uuid(), u.id, r.id
          FROM iam.user_account u, iam.role r
         WHERE r.code = 'admin'
        ON CONFLICT (user_id, role_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM iam.user_role
         WHERE role_id IN (SELECT id FROM iam.role
                            WHERE code IN ('admin', 'modeller', 'planner', 'viewer'));
        DROP TABLE iam.role_capability;
        DROP TABLE iam.capability;
        DELETE FROM iam.role WHERE code IN ('admin', 'modeller', 'planner', 'viewer');
        """
    )
