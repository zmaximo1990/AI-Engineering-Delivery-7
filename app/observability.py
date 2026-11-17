"""Interchangeable tracing providers selected by ``OBSERVABILITY_PROVIDER``."""

from __future__ import annotations

import logging
import os
from typing import Protocol

from app.settings import settings

logger = logging.getLogger(__name__)


class TraceProvider(Protocol):
    """Common lifecycle for observability backends."""

    def setup(self) -> None: ...

    def shutdown(self) -> None: ...


class LangSmithProvider:
    """Enable LangChain/LangGraph tracing to LangSmith via env vars."""

    def setup(self) -> None:
        api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()
        if api_key:
            # LangChain tracing still reads LANGCHAIN_API_KEY.
            os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
        if not api_key:
            logger.warning("LangSmith selected but LANGSMITH_API_KEY is empty")
        else:
            logger.info(
                "Observability: LangSmith project=%s",
                os.environ.get("LANGCHAIN_PROJECT"),
            )

    def shutdown(self) -> None:
        return None


class PhoenixProvider:
    """Export LangChain spans to an Arize Phoenix collector via OpenInference."""

    def __init__(self) -> None:
        self._instrumentor = None
        self._tracer_provider = None

    def setup(self) -> None:
        # Avoid double-shipping to LangSmith when Phoenix is the active provider.
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry import trace as trace_api
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = settings.phoenix_collector_endpoint
        resource = Resource.create({"service.name": settings.langchain_project})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace_api.set_tracer_provider(provider)

        instrumentor = LangChainInstrumentor()
        instrumentor.instrument(tracer_provider=provider)
        self._instrumentor = instrumentor
        self._tracer_provider = provider
        logger.info("Observability: Phoenix OTLP endpoint=%s", endpoint)

    def shutdown(self) -> None:
        if self._instrumentor is not None:
            try:
                self._instrumentor.uninstrument()
            except Exception:  # pragma: no cover
                logger.exception("Phoenix uninstrument failed")
            self._instrumentor = None
        if self._tracer_provider is not None:
            try:
                self._tracer_provider.shutdown()
            except Exception:  # pragma: no cover
                logger.exception("Phoenix tracer shutdown failed")
            self._tracer_provider = None


def get_trace_provider() -> TraceProvider:
    """Build the provider named by ``settings.observability_provider``."""
    name = settings.observability_provider
    if name == "langsmith":
        return LangSmithProvider()
    if name == "phoenix":
        return PhoenixProvider()
    raise ValueError(f"Unknown OBSERVABILITY_PROVIDER: {name}")


def setup_observability() -> TraceProvider:
    """Initialize tracing once at API startup."""
    provider = get_trace_provider()
    provider.setup()
    return provider
