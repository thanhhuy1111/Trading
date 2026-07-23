from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from packages.common.logger import logger
from packages.telemetry.models import TelemetryContext


class Span:
    """Represents a telemetry tracing span."""

    def __init__(self, name: str, context: TelemetryContext) -> None:
        self.name = name
        self.context = context
        self.start_time = datetime.now(timezone.utc)
        self.end_time: Optional[datetime] = None
        self.attributes: Dict[str, Any] = {}
        self.status = "OK"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = str(value)

    def finish(self, status: str = "OK") -> None:
        self.status = status
        self.end_time = datetime.now(timezone.utc)
        duration_ms = (self.end_time - self.start_time).total_seconds() * 1000.0
        logger.debug(
            "Span finished",
            extra={
                "span_name": self.name,
                "duration_ms": duration_ms,
                "status": status,
                "trace_id": self.context.trace_id,
            }
        )


class Tracer:
    """OpenTelemetry-compatible tracer."""

    @contextmanager
    def start_span(self, name: str, context: Optional[TelemetryContext] = None) -> Generator[Span, None, None]:
        ctx = context or TelemetryContext()
        span = Span(name, ctx)
        try:
            yield span
            span.finish("OK")
        except Exception as exc:
            span.finish("ERROR")
            raise exc


tracer = Tracer()
