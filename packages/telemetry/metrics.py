from typing import Dict, List

ALLOWED_LABEL_KEYS = {
    "service",
    "environment",
    "exchange",
    "symbol",
    "timeframe",
    "component",
    "result",
    "reason_code",
    "status",
    "mode",
}


class MetricsRegistry:
    """Prometheus-compatible metrics registry with strict cardinality budget enforcement."""

    def __init__(self) -> None:
        self.counters: Dict[str, float] = {}
        self.gauges: Dict[str, float] = {}

    def _format_key(self, name: str, labels: Dict[str, str]) -> str:
        # Validate label key cardinality policy
        for k in labels.keys():
            if k not in ALLOWED_LABEL_KEYS:
                raise ValueError(f"CARDINALITY_POLICY_VIOLATION: Label key '{k}' is forbidden in Prometheus metrics")

        label_strs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        lbl_part = "{" + ",".join(label_strs) + "}" if label_strs else ""
        return f"{name}{lbl_part}"

    def increment_counter(self, name: str, labels: Dict[str, str], amount: float = 1.0) -> None:
        key = self._format_key(name, labels)
        self.counters[key] = self.counters.get(key, 0.0) + amount

    def set_gauge(self, name: str, labels: Dict[str, str], value: float) -> None:
        key = self._format_key(name, labels)
        self.gauges[key] = value

    def export_prometheus_text(self) -> str:
        lines: List[str] = []
        for key, val in self.counters.items():
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {val}")
        for key, val in self.gauges.items():
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {val}")
        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()
