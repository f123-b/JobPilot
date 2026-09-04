from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from ..config import settings

_tracer: Any = None


def configure_telemetry(app: Any) -> dict[str, Any]:
    """Configure optional OpenTelemetry tracing.

    Local task/usage metrics remain available even when OTEL is disabled or optional
    packages are not installed. This keeps the demo mode dependency-light.
    """
    global _tracer
    if not settings.otel_enabled:
        return {"enabled": False, "reason": "OTEL_ENABLED=false"}
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        if settings.otel_exporter_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
        else:
            exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("jobpilot")
        FastAPIInstrumentor.instrument_app(app)
        return {"enabled": True, "exporter": "otlp" if settings.otel_exporter_endpoint else "console"}
    except Exception as exc:  # pragma: no cover - optional integration
        return {"enabled": False, "reason": str(exc)}


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield
