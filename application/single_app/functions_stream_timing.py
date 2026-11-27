# functions_stream_timing.py
"""Opt-in timing for one SSE response, without recording chat payloads."""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from time import perf_counter_ns
from typing import ParamSpec, TypeVar
from uuid import uuid4


_P = ParamSpec("_P")
_T = TypeVar("_T")
_Field = str | int | float | bool


def _milliseconds(nanoseconds: int) -> float:
    return round(nanoseconds / 1_000_000, 3)


class PhaseTimings:
    """Accumulate timings owned by a single producer or consumer."""

    def __init__(self) -> None:
        self._phases: dict[str, tuple[int, int, int]] = {}

    @contextmanager
    def measure(self, phase: str) -> Iterator[None]:
        start = perf_counter_ns()
        try:
            yield
        finally:
            elapsed = perf_counter_ns() - start
            count, total, maximum = self._phases.get(phase, (0, 0, 0))
            self._phases[phase] = (count + 1, total + elapsed, max(maximum, elapsed))

    def call(self, phase: str, function: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        with self.measure(phase):
            return function(*args, **kwargs)

    def iterate(self, source: Iterable[_T], phase: str) -> Iterator[_T]:
        iterator = iter(source)
        while True:
            try:
                item = self.call(phase, next, iterator)
            except StopIteration:
                return
            yield item

    def properties(self) -> dict[str, _Field]:
        fields: dict[str, _Field] = {}
        for phase, (count, total, maximum) in self._phases.items():
            fields[f"{phase}_count"] = count
            fields[f"{phase}_total_ms"] = _milliseconds(total)
            fields[f"{phase}_max_ms"] = _milliseconds(maximum)
        return fields


class StreamTiming:
    def __init__(self, log: Callable[[str, dict[str, _Field]], None]) -> None:
        self.run_id = uuid4().hex[:16]
        self.producer = PhaseTimings()
        self.consumer = PhaseTimings()
        self._log = log
        self._origin = perf_counter_ns()
        self._event_sequence = 0
        self._last_yield_ms = 0.0

    def start(self, redis_selected: bool) -> None:
        self._emit("start", {"redis_selected": redis_selected})

    def mark_yield(self, event: str) -> str:
        if not event.startswith("data:"):
            return event
        self._event_sequence += 1
        self._last_yield_ms = _milliseconds(perf_counter_ns() - self._origin)
        sequence = self._event_sequence
        if sequence != 1 and (sequence % 128 or sequence > 4096):
            return event
        with self.consumer.measure("yield_log"):
            self._emit("yield", {"event_sequence": sequence, "elapsed_ms": self._last_yield_ms})
        return f": sc-timing {sequence}\n{event}"

    @contextmanager
    def report_on_exit(self, actor: str, phases: PhaseTimings) -> Iterator[None]:
        start = perf_counter_ns()
        try:
            yield
        finally:
            fields = phases.properties()
            fields["actor_wall_ms"] = _milliseconds(perf_counter_ns() - start)
            fields["actor_start_ms"] = _milliseconds(start - self._origin)
            if phases is self.consumer:
                fields["event_count"] = self._event_sequence
                fields["last_yield_ms"] = self._last_yield_ms
            self._emit(actor, fields)

    def _emit(self, stage: str, fields: dict[str, _Field]) -> None:
        self._log(f"[STREAMING] Timing {stage}", {"diagnostic_run_id": self.run_id, **fields})
