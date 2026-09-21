"""Display names, frozen with the data (migration 0012).

`ahmed` is a spelling the platform chose; `Ahmed Salah` is the person. An
answer printed in keys is readable only by whoever wrote the keys.

The two properties worth pinning are both about *not* letting a display
concern reach the solver:

- labels live beside the set rows, never merged into them, so a domain
  attribute called `label` and an entity's own label cannot shadow each
  other;
- they are frozen with the run, so renaming someone tomorrow does not rewrite
  an answer given today.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text

from tests.test_v1_problem_run import (  # noqa: F401
    _data,
    _snapshot,
    db,
    make_attribute_def,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_problem,
)


def _fixture(db):
    domain = make_domain(db, "labels")
    employee = make_entity_type(db, domain, "employee", "agent")
    make_attribute_def(db, employee, "hours_per_week", "integer")
    make_entity(db, employee, "ahmed", label="Ahmed Salah", attrs={"hours_per_week": 40})
    make_entity(db, employee, "sara", label="Sara Nabil", attrs={"hours_per_week": 32})
    ir = {
        "version": 1,
        "sets": ["employee"],
        "parameters": {},
        "variables": {"pick": {"index": ["employee"], "domain": "binary"}},
        "constraints": [],
    }
    problem = make_problem(db, domain)
    return domain, employee, make_model_version(db, problem, ir)


def test_a_snapshot_carries_the_names_people_read(db):
    _, _, version = _fixture(db)

    data = _data(db, _snapshot(db, version))

    assert data["labels"]["employee"] == {"ahmed": "Ahmed Salah", "sara": "Sara Nabil"}


def test_labels_sit_beside_the_set_rows_rather_than_inside_them(db):
    """The set rows feed the compiler. A label merged into them could collide
    with a domain attribute, and a display concern would then change what is
    solved."""
    _, _, version = _fixture(db)

    data = _data(db, _snapshot(db, version))

    for row in data["sets"]["employee"]:
        assert "label" not in row
    assert set(data["sets"]["employee"][0]) == {"id", "hours_per_week"}


def test_an_entity_with_no_label_is_absent_rather_than_null(db):
    """The reader falls back to the key, which is what it would have to do for
    a null anyway."""
    domain, employee, version = _fixture(db)
    make_entity(db, employee, "nameless", attrs={"hours_per_week": 10})

    data = _data(db, _snapshot(db, version))

    assert "nameless" not in data["labels"]["employee"]
    assert any(row["id"] == "nameless" for row in data["sets"]["employee"])


def test_renaming_someone_does_not_rewrite_an_answer_already_given(db):
    """The point of freezing them. A run answers the question as it was asked,
    and that includes what things were called at the time."""
    _, employee, version = _fixture(db)
    before = _data(db, _snapshot(db, version))

    db.execute(
        text("UPDATE entity SET label = 'Ahmed S.' WHERE key = 'ahmed' AND entity_type_id = :t"),
        {"t": employee},
    )
    db.commit()
    after = _data(db, _snapshot(db, version))

    assert before["labels"]["employee"]["ahmed"] == "Ahmed Salah"
    assert after["labels"]["employee"]["ahmed"] == "Ahmed S."


def test_an_inactive_entity_is_left_out_of_the_labels_too(db):
    """`sets` excludes it, so a label for it would name something the answer
    cannot contain."""
    _, employee, version = _fixture(db)
    db.execute(
        text("UPDATE entity SET active = false WHERE key = 'sara' AND entity_type_id = :t"),
        {"t": employee},
    )
    db.commit()

    data = _data(db, _snapshot(db, version))

    assert "sara" not in data["labels"]["employee"]
    assert "sara" not in {row["id"] for row in data["sets"]["employee"]}


def test_0012_carries_0011s_statement_byte_for_byte(db):
    """`downgrade()` restores 0011's function from a copy. If the copy drifts,
    the downgrade silently installs something 0011 never installed."""
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    pattern = r'_SNAPSHOT_DATASET_0011 = """\n(.*?)"""\n'
    in_0011 = re.search(
        pattern, (versions / "0011_snapshot_relationships.py").read_text(encoding="utf-8"), re.S
    )
    in_0012 = re.search(
        pattern, (versions / "0012_snapshot_labels.py").read_text(encoding="utf-8"), re.S
    )

    assert in_0011 and in_0012
    assert in_0012.group(1) == in_0011.group(1)
