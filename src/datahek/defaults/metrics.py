"""LocalMetrics — in-process Prometheus-style metrics with zero dependencies.

Counters and summaries rendered in the Prometheus text exposition format.
OSS default replaces nothing — Enterprise swaps in its own metrics backend
via the composition root.
"""
import threading
import time


class LocalMetrics:
    def __init__(self) -> None:
        self._counters: dict[tuple, float] = {}
        self._summaries: dict[tuple, tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._started = time.time()

    @staticmethod
    def _key(name: str, labels: dict) -> tuple:
        return (name, tuple(sorted((k, str(v)) for k, v in labels.items())))

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            total, count = self._summaries.get(key, (0.0, 0))
            self._summaries[key] = (total + value, count + 1)

    @staticmethod
    def _format_labels(labels: tuple) -> str:
        if not labels:
            return ""
        inner = ",".join(f'{k}="{v}"' for k, v in labels)
        return "{" + inner + "}"

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            summaries = dict(self._summaries)

        seen_types: set[str] = set()
        for (name, labels), value in sorted(counters.items()):
            if name not in seen_types:
                lines.append(f"# TYPE {name} counter")
                seen_types.add(name)
            lines.append(f"{name}{self._format_labels(labels)} {value:g}")
        for (name, labels), (total, count) in sorted(summaries.items()):
            if name not in seen_types:
                lines.append(f"# TYPE {name} summary")
                seen_types.add(name)
            lines.append(f"{name}_sum{self._format_labels(labels)} {total:g}")
            lines.append(f"{name}_count{self._format_labels(labels)} {count}")
        lines.append("# TYPE datahek_uptime_seconds gauge")
        lines.append(f"datahek_uptime_seconds {time.time() - self._started:.3f}")
        lines.append("")
        return "\n".join(lines)
