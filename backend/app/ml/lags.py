"""Lags: a record's value some steps earlier in time, as an input to a forecast (benchmark re-test,
October 2026: time-series features -- yesterday's demand, last week's -- were not to be had).

Records are put in time order by a field (a date, or a number), kept apart by another (each store's
own days), and each takes `<field>_lag<k>`: the value of `field` k records earlier in its series, or
nothing when the series is not that long. A record with no time is in no series and has no lags.

When forecasting, the future records have no value of their own yet: `Series.push` takes each
record's actual value when it has one and the forecast made for it otherwise, so day t+2 reads the
forecast of day t+1 -- one step after another.
"""

from __future__ import annotations

import math
from typing import Any, Callable

#: The most lags one forecast takes, and the furthest back.
MAX_LAGS = 5
MAX_STEP = 366


def name(field: str, step: int) -> str:
    return f"{field}_lag{step}"


def when(value: Any) -> tuple[int, Any] | None:
    """A sortable time: a number, or text (ISO dates sort as text). None for no time."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return (0, float(value)) if math.isfinite(float(value)) else None
    text = str(value).strip()
    return (1, text) if text else None


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def ordered(records: list[Any], attrs_of: Callable[[Any], dict[str, Any]], order_by: str, group_by: str | None
            ) -> list[tuple[Any, Any]]:
    """(series, record) in time order within each series; records without a time are left out."""
    timed = []
    for record in records:
        attrs = attrs_of(record)
        at = when(attrs.get(order_by))
        if at is not None:
            timed.append(((str(attrs.get(group_by)) if group_by else "", at), record))
    timed.sort(key=lambda pair: pair[0])
    return [(series, record) for (series, _), record in timed]


class Series:
    """Each series' values so far, newest last."""

    def __init__(self, steps: list[int]):
        self.steps = steps
        self.seen: dict[Any, list[float | None]] = {}

    def lags(self, series: Any) -> list[float | None]:
        past = self.seen.get(series, [])
        return [past[-k] if len(past) >= k else None for k in self.steps]

    def push(self, series: Any, value: float | None) -> None:
        self.seen.setdefault(series, []).append(value)


def add(rows: list[dict[str, Any]], field: str, steps: list[int], order_by: str, group_by: str | None) -> list[dict[str, Any]]:
    """Training rows with their lags: each row a copy, `field_lag<k>` set where the series reaches back."""
    out = [dict(row) for row in rows]
    series = Series(steps)
    for key, row in ordered(out, lambda r: r, order_by, group_by):
        for step, value in zip(steps, series.lags(key)):
            row[name(field, step)] = value
        series.push(key, number(row.get(field)))
    return out
