from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_iam_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="iam"))
    # `capability` and `role_capability` are migration 0013: a role holds
    # capabilities, and the API checks for those by name rather than for a
    # role, so the policy lives in one place.
    assert tables == {
        "organization",
        "user_account",
        "role",
        "user_role",
        "capability",
        "role_capability",
        # Migration 0034: per-organization limits, and what each used.
        "quota",
        "usage_month",
        # Migration 0035: keys for programs, and the rate limit's buckets.
        "api_key",
        "rate_bucket",
        # Migration 0071: an organization's own licences for added solvers (queue R42).
        "solver_licence",
        # Migration 0077: append-only audit log (queue R34).
        "audit_event",
        # Migration 0079: an organization's SSO provider and SCIM bearer tokens.
        "oidc_provider",
        "scim_token",
    }
