from sqlalchemy.exc import IntegrityError


def conflict_detail(exc: IntegrityError, table: str) -> str:
    """Translate a Postgres IntegrityError into a user-facing 409 message.

    Handles the three conflict classes the generic CRUD router can hit:
    foreign_key_violation (23503) on both delete (parent still referenced)
    and create/update (bad reference), unique_violation (23505), and
    not_null_violation (23502). Anything else falls back to a generic
    message rather than leaking the raw database error.
    """
    diag = getattr(exc.orig, "diag", None)
    code = getattr(exc.orig, "pgcode", "") or ""
    constraint = (getattr(diag, "constraint_name", None) or "") if diag else ""
    if code == "23503":  # foreign_key_violation
        # deleting a parent vs inserting a child with a bad reference
        if diag is not None and diag.table_name and diag.table_name != table:
            return f"{table} row is still referenced by {diag.table_name} records"
        column = (
            (getattr(diag, "message_detail", "") or "").split("(")[1].split(")")[0]
            if diag and "(" in (getattr(diag, "message_detail", "") or "")
            else "a referenced row"
        )
        return f"referenced {column} does not exist"
    if code == "23505":  # unique_violation
        cols = constraint.replace(f"{table}_", "").replace("_key", "").replace("uq_", "")
        return f"a {table} row with the same {cols or 'unique value'} already exists"
    if code == "23502":  # not_null_violation
        return f"{getattr(diag, 'column_name', 'a required field')} is required"
    # A check constraint or a trigger's own rule (a relationship's cardinality, an attribute's type): say which,
    # in the database's words -- they are the platform's own messages about the person's own records. "The change
    # conflicts with existing data" alone was refused six times running in the phase 1 evaluation (10 October
    # 2026), and the Assistant never learned what to change.
    primary = (getattr(diag, "message_primary", None) or "").strip() if diag else ""
    detail = (getattr(diag, "message_detail", None) or "").strip() if diag else ""
    where = (getattr(diag, "table_name", None) or table) if diag else table
    said = "; ".join(x for x in (primary, detail) if x)
    if said:
        return f"the change to {where} breaks a rule{f' ({constraint})' if constraint else ''}: {said}"[:500]
    return f"the change to {where} conflicts with existing data{f' (rule {constraint})' if constraint else ''}"
