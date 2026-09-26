"""Chunked amounts helpers (OAAS Phase 5)."""

from __future__ import annotations

from app.solve import service


def test_amount_chunk_rows_split_by_chunk_size():
    amounts = {
        "kg": [{"index": [str(i)], "value": i} for i in range(5)],
        "trucks": [{"index": ["a"], "value": 2}],
    }
    chunks = service._amount_chunk_rows(amounts, chunk_size=2)
    assert [c[0:2] + (c[3],) for c in chunks] == [
        ("kg", 0, 2),
        ("kg", 1, 2),
        ("kg", 2, 1),
        ("trucks", 0, 1),
    ]
