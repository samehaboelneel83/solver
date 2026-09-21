"""A live read of the domain in the snapshot's JSON shape.

`compile_model` needs a dataset to tell a vacuous `forall` from a real one.
`snapshot_dataset()` is the run's freeze, and it INSERTs. The editor asks
this on every well-shaped draft, so it cannot call that. The SQL is the
same loops migration 0016 uses; the difference is there is no hash and no
row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def live_data(db: Session, domain_id: int, ir: dict[str, Any]) -> dict[str, Any]:
    """What `snapshot_dataset()` would freeze, without writing it.

    Unknown set / parameter / relationship names become empty collections
    rather than the snapshot's RAISE: a draft is allowed to be unfinished,
    and compile then reports the empty range instead of the editor 500ing.
    """
    sets: dict[str, Any] = {}
    labels: dict[str, Any] = {}
    for name in _names(ir.get("sets")):
        sets[name] = _json(
            db,
            """
            SELECT coalesce(jsonb_agg(jsonb_build_object('id', e.key) || e.attrs
                                      ORDER BY e.sort_order, e.key), '[]')
              FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
             WHERE t.domain_id = :d AND t.name = :n AND e.active
            """,
            domain_id,
            name,
            default=[],
        )
        labels[name] = _json(
            db,
            """
            SELECT coalesce(jsonb_object_agg(e.key, e.label), '{}')
              FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
             WHERE t.domain_id = :d AND t.name = :n AND e.active
               AND e.label IS NOT NULL
            """,
            domain_id,
            name,
            default={},
        )

    parameters: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for name in (ir.get("parameters") or {}) if isinstance(ir.get("parameters"), dict) else {}:
        parameters[name] = _json(
            db,
            """
            SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]')
              FROM (
                SELECT CASE
                         WHEN bigint_array_is_distinct(pd.index_type_ids)
                         THEN jsonb_object_agg(t.name, e.key)
                         ELSE jsonb_object_agg((u.ord - 1)::text, e.key)
                       END
                       || jsonb_build_object('value', trim_scale(pv.value)) AS row_json
                  FROM parameter_def pd
                  JOIN parameter_value pv ON pv.parameter_def_id = pd.id
                  CROSS JOIN LATERAL unnest(pv.entity_ids) WITH ORDINALITY AS u(eid, ord)
                  JOIN entity e ON e.id = u.eid
                  JOIN entity_type t ON t.id = e.entity_type_id
                 WHERE pd.domain_id = :d AND pd.name = :n
                 GROUP BY pv.parameter_def_id, pv.entity_ids, pv.value, pd.index_type_ids
                HAVING bool_and(e.active)
              ) q
            """,
            domain_id,
            name,
            default=[],
        )
        default = db.execute(
            text(
                """
                SELECT (jsonb_build_object('v', trim_scale(pd.default_value))) -> 'v'
                  FROM parameter_def pd
                 WHERE pd.domain_id = :d AND pd.name = :n
                """
            ),
            {"d": domain_id, "n": name},
        ).scalar()
        defaults[name] = 0 if default is None else default

    relationships: dict[str, Any] = {}
    for name in _names(ir.get("relationships")):
        # Always keyed, even when empty: compile refuses a declared type
        # that the dataset does not carry at all.
        relationships[name] = _json(
            db,
            """
            SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]')
              FROM (
                SELECT jsonb_build_object('from', ef.key, 'to', et.key)
                       || CASE WHEN r.valid_from IS NULL THEN '{}'::jsonb
                               ELSE jsonb_build_object('valid_from', r.valid_from) END
                       || CASE WHEN r.valid_to IS NULL THEN '{}'::jsonb
                               ELSE jsonb_build_object('valid_to', r.valid_to) END
                       || CASE WHEN r.attrs = '{}'::jsonb THEN '{}'::jsonb
                               ELSE jsonb_build_object('attrs', r.attrs) END AS row_json
                  FROM relationship r
                  JOIN relationship_type rt ON rt.id = r.relationship_type_id
                  JOIN entity ef ON ef.id = r.from_entity_id
                  JOIN entity et ON et.id = r.to_entity_id
                 WHERE rt.domain_id = :d AND rt.name = :n
                   AND ef.active AND et.active
              ) q
            """,
            domain_id,
            name,
            default=[],
        )

    return {
        "labels": labels,
        "sets": sets,
        "parameters": parameters,
        "parameter_defaults": defaults,
        "relationships": relationships,
    }


def _names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for name in value if isinstance(name, str)]


def _json(
    db: Session, sql: str, domain_id: int, name: str, *, default: Any
) -> Any:
    found = db.execute(text(sql), {"d": domain_id, "n": name}).scalar()
    return default if found is None else found
