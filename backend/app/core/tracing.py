"""OpenTelemetry traces: one trace from the request that queued a run to the worker that solved it.

A run crosses two processes and a queue. The API's span for the request
that submitted it is the root; `enqueue_run` injects that trace's context
into `run.params.trace` (W3C `traceparent`), and the worker, claiming the
run minutes or hours later, continues the same trace from it. Under the
worker's `run` span sit one span per stage -- `compile`, `choose`, `solve`,
`diagnose` (infeasible runs only) and `persist` -- so where a run's time
went is one picture, not two logs to line up by hand.

**Where spans go** is `OTEL_TRACES_EXPORTER`:

* `log` (default) -- each finished span becomes a JSON log line (`event:
  "span"`, with its trace and parent ids and duration), through the same
  logger as everything else: readable with no collector running;
* `otlp` -- to an OpenTelemetry collector over HTTP, at
  `OTEL_EXPORTER_OTLP_ENDPOINT` (the SDK's own variable);
* `none` -- spans are made, so contexts still propagate, but not exported.

The provider is this module's own rather than the global one, so a test can
swap its exporter without fighting OpenTelemetry's set-once rule.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()
_tracer: trace.Tracer | None = None


class LogExporter(SpanExporter):
    """Each span as one JSON log line, for a deployment with no collector."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        from app.core import logs

        log = logs.get("solver.trace")
        for span in spans:
            ctx = span.get_span_context()
            log.info(
                "span",
                name=span.name,
                trace_id=format(ctx.trace_id, "032x"),
                span_id=format(ctx.span_id, "016x"),
                parent_id=format(span.parent.span_id, "016x") if span.parent else None,
                duration_ms=round((span.end_time - span.start_time) / 1e6, 2),
                status=span.status.status_code.name.lower(),
                **{f"attr.{k}": v for k, v in (span.attributes or {}).items()},
            )
        return SpanExportResult.SUCCESS


def configure(service: str, *, exporter: SpanExporter | None = None) -> None:
    """Set this process's tracer. `exporter` overrides the environment (tests)."""
    global _tracer
    provider = TracerProvider(resource=Resource.create({"service.name": f"solver-{service}"}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        kind = os.environ.get("OTEL_TRACES_EXPORTER", "log")
        if kind == "log":
            provider.add_span_processor(SimpleSpanProcessor(LogExporter()))
        elif kind == "otlp":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        elif kind != "none":
            raise ValueError(f"OTEL_TRACES_EXPORTER is log, otlp or none, not {kind!r}")
    _tracer = provider.get_tracer("solver")


def tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        # Unconfigured (a script, a test): spans with ids, exported nowhere.
        _tracer = TracerProvider().get_tracer("solver")
    return _tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    clean = {k: v for k, v in attributes.items() if v is not None}
    with tracer().start_as_current_span(name, attributes=clean) as current:
        yield current


def carrier() -> dict[str, str]:
    """The current trace context as `{"traceparent": ...}`, for a run's params."""
    found: dict[str, str] = {}
    _PROPAGATOR.inject(found)
    return found


@contextmanager
def continued(found: dict[str, str] | None) -> Iterator[None]:
    """Make the trace in `found` current, so spans opened inside join it. A
    run queued before tracing existed has none and starts its own trace."""
    token = context.attach(_PROPAGATOR.extract(found or {}))
    try:
        yield
    finally:
        context.detach(token)


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
