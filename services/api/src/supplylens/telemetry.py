"""OpenTelemetry tracing.

Inactive unless an OTLP/HTTP endpoint is configured (`SUPPLYLENS_OTEL_ENDPOINT`, e.g. http://collector:4318), in
which case spans for HTTP requests, SQL and outbound HTTP are exported, plus spans for the business operations
(agent nodes, forecasts, retrieval, dispatch, jobs). The trace context is stored on each queued job, so a worker's
spans join the trace of the request that enqueued the work. Spans never carry request bodies or SQL parameter values.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from .config import settings

log = logging.getLogger("supplylens.telemetry")
_provider: TracerProvider | None = None
_instrumented_apps: set[int] = set()
VERSION = "0.1.0"


def tracer():
    return trace.get_tracer("supplylens", VERSION)


def setup(app=None, *, exporter: SpanExporter | None = None, service_name: str | None = None) -> TracerProvider | None:
    """Install the tracer provider once per process and instrument `app`. Returns None when tracing is off."""
    global _provider
    endpoint = settings.otel_endpoint
    if exporter is None and not endpoint:
        return None
    if _provider is None:
        resource = Resource.create({"service.name": service_name or settings.otel_service_name,
                                    "service.version": VERSION})
        provider = TracerProvider(resource=resource)
        if exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
        trace.set_tracer_provider(provider)
        _provider = provider
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        _trace_sql()
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        log.info("tracing enabled: %s", endpoint or "in-memory exporter")
    if app is not None and id(app) not in _instrumented_apps:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider, excluded_urls="health")
        _instrumented_apps.add(id(app))
    return _provider


def _trace_sql() -> None:
    """One client span per SQL statement via SQLAlchemy's public cursor events (the OpenTelemetry SQLAlchemy
    package does not support SQLAlchemy 2.1). Only the operation is recorded: never statement text or parameters."""
    from opentelemetry.trace import SpanKind, Status, StatusCode
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):
        words = statement.lstrip().split(None, 1)
        op = words[0].upper() if words else "SQL"
        sp = tracer().start_span(f"db {op}", kind=SpanKind.CLIENT,
                                 attributes={"db.system": "postgresql", "db.operation": op})
        context._sl_span = sp

    @event.listens_for(Engine, "after_cursor_execute")
    def _end(conn, cursor, statement, parameters, context, executemany):
        sp = getattr(context, "_sl_span", None)
        if sp is not None:
            sp.end()

    @event.listens_for(Engine, "handle_error")
    def _fail(exc_context):
        sp = getattr(exc_context.execution_context, "_sl_span", None)
        if sp is not None:
            sp.set_status(Status(StatusCode.ERROR, type(exc_context.original_exception).__name__))
            sp.end()


def shutdown() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def inject_context() -> dict:
    """W3C trace context of the current span, to be stored with queued work."""
    carrier: dict = {}
    inject(carrier)
    return carrier


@contextmanager
def span(name: str, **attributes):
    """A child span of whatever is current; a no-op recorder when tracing is off."""
    with tracer().start_as_current_span(name) as s:
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(k, v if isinstance(v, (str, bool, int, float)) else str(v))
        yield s


@contextmanager
def continue_trace(carrier: dict | None, name: str, **attributes):
    """Run a block as a span in the trace described by `carrier` (a queued job's stored context)."""
    token = otel_context.attach(extract(carrier or {}))
    try:
        with span(name, **attributes) as s:
            yield s
    finally:
        otel_context.detach(token)
