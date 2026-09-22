"""One JSON object per log line, from the API and the worker alike (target roadmap Phase 8).

    {"event": "run solved", "level": "info", "timestamp": "...", "service": "worker",
     "run_id": 42, "org_id": "…", "solver": "cp-sat", "status": "optimal", ...}

`configure("api" | "worker")` sets it up once per process. Everything goes
through the same renderer -- structlog calls, the standard library's
`logging.getLogger(...)` calls in older modules, uvicorn's own lines -- so a
log collector never meets two formats.

**Context is bound, not repeated.** `bind(run_id=..., org_id=...)` puts
fields on every line logged until `clear()`: the worker binds a run's id and
organization when it claims it, and the solver once one is chosen, so every
line about that run carries all three without each call site passing them.
They live in context variables, so one thread's run never leaks into
another's lines.

`LOG_FORMAT=console` gives a readable, coloured line instead, for a person
at a terminal; JSON is the default because the default reader is a machine.
`LOG_LEVEL` sets the threshold (default INFO).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

def _add_trace(_logger, _method, event: dict[str, Any]) -> dict[str, Any]:
    """The trace this line belongs to (`app.core.tracing`), when there is one."""
    from app.core.tracing import current_trace_id

    found = current_trace_id()
    if found:
        event.setdefault("trace_id", found)
    return event


_SHARED = [
    structlog.contextvars.merge_contextvars,
    _add_trace,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
]


def configure(service: str, *, stream=None) -> None:
    """Route every logger in this process to one JSON (or console) renderer,
    with `service` on each line. Safe to call again, e.g. from a test with its
    own stream."""
    renderer = (
        structlog.dev.ConsoleRenderer()
        if os.environ.get("LOG_FORMAT", "json") == "console"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[*_SHARED, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # Lines from the standard library get the same fields as ours.
        foreign_pre_chain=_SHARED,
        processors=[
            _add_service(service),
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    # uvicorn installs its own handlers; send its lines through ours. Its
    # access log is replaced by the API's request line, which knows the
    # organization and the time taken.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False


def _add_service(service: str):
    def processor(_logger, _method, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("service", service)
        return event

    return processor


def get(name: str | None = None):
    return structlog.get_logger(name)


def bind(**fields: Any) -> None:
    structlog.contextvars.bind_contextvars(**{k: v for k, v in fields.items() if v is not None})


def clear() -> None:
    structlog.contextvars.clear_contextvars()
