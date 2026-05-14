"""Lightweight observability for renderer hot paths.

Disabled by default — a `stats.tick(name)` call when disabled is a single
attribute check (~10ns). Turn on for tools or assertions:

    from ptedit.stats import stats
    stats.enabled = True
    # ... run workload ...
    print(stats.report())
"""
from __future__ import annotations


class Stats:
    def __init__(self) -> None:
        self.enabled: bool = False
        self._counters: dict[str, int] = {}
        self._samples: dict[str, list[float]] = {}

    def tick(self, name: str) -> None:
        if self.enabled:
            self._counters[name] = self._counters.get(name, 0) + 1

    def sample(self, name: str, value: float) -> None:
        if self.enabled:
            self._samples.setdefault(name, []).append(value)

    def reset(self) -> None:
        self._counters.clear()
        self._samples.clear()

    def counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    def samples(self, name: str) -> list[float]:
        return self._samples.get(name, [])

    def report(self) -> str:
        lines: list[str] = []
        for k in sorted(self._counters):
            lines.append(f"{k}: {self._counters[k]}")
        for k in sorted(self._samples):
            vs = self._samples[k]
            lines.append(
                f"{k}: n={len(vs)} avg={sum(vs)/len(vs):.1f} min={min(vs)} max={max(vs)}"
            )
        return "\n".join(lines)


stats = Stats()
