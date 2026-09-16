"""OpenTelemetry spans for runs, LLM calls and tool calls.

If the OpenTelemetry SDK is not installed the tracer is a no-op: measurements
must never be the reason a run fails.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any


class _NoopSpan:
    def set_attribute(self, _key: str, _value: Any) -> None:
        return None


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a span named *name* with *attributes*; no-op without OpenTelemetry."""
    try:
        from opentelemetry import trace
    except ImportError:
        yield _NoopSpan()
        return
    tracer = trace.get_tracer("regent")
    with tracer.start_as_current_span(name) as otel_span:
        for key, value in attributes.items():
            otel_span.set_attribute(key, value)
        yield otel_span


def configure_otlp(endpoint: str | None = None, service_name: str = "regent") -> bool:
    """Install an OTLP/HTTP exporter. Returns False when the SDK is missing."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return True
