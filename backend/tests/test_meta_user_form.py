"""Operator trial F20: a new-user form asks only for what a person should type."""
from __future__ import annotations

from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_new_user_form_has_no_sso_subject_or_sign_out_counter(client, auth_headers):  # noqa: F811
    tables = client.get("/api/meta/schema", headers=auth_headers).json()
    user = next(t for t in tables if t["schema"] == "iam" and t["table"] == "user_account")
    writable = {f["name"] for f in user["fields"] if f["writable"]}
    assert {"username", "password"} <= writable
    assert not writable & {"external_sub", "token_version"}
