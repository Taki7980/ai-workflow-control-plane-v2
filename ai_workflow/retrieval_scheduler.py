from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class ScheduledCall(Generic[T]):
    label: str
    fn: Callable[[], T]


@dataclass(frozen=True)
class SchedulerOutcome(Generic[T]):
    label: str
    value: T | None = None
    latency_ms: float = 0.0
    error: str | None = None
    error_kind: str | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out


class BoundedRetrievalScheduler:
    """Runs blocking retrieval adapters concurrently with one global deadline.

    Blocking callables execute through ``asyncio.to_thread``. Cancelling the
    asyncio wrapper cannot forcibly stop arbitrary Python blocking code already
    executing in a worker thread; command providers therefore retain their own
    process-level timeouts as the hard resource boundary.
    """

    def __init__(self, max_concurrency: int = 4):
        if isinstance(max_concurrency, bool) or int(max_concurrency) < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.max_concurrency = int(max_concurrency)

    async def run(self, calls: list[ScheduledCall[T]], deadline_seconds: float) -> list[SchedulerOutcome[T]]:
        if float(deadline_seconds) <= 0:
            raise ValueError("deadline_seconds must be > 0")
        if not calls:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrency)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(deadline_seconds)

        async def execute(call: ScheduledCall[T]) -> SchedulerOutcome[T]:
            started = time.perf_counter()
            try:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                async with semaphore:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    value = await asyncio.wait_for(asyncio.to_thread(call.fn), timeout=remaining)
                return SchedulerOutcome(
                    label=call.label,
                    value=value,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except asyncio.TimeoutError:
                return SchedulerOutcome(
                    label=call.label,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=f"global retrieval deadline exceeded after {deadline_seconds:g} seconds",
                    error_kind="deadline",
                    timed_out=True,
                )
            except Exception as exc:  # retrieval adapters are failure-isolated
                return SchedulerOutcome(
                    label=call.label,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                    error_kind="exception",
                )

        tasks = [asyncio.create_task(execute(call)) for call in calls]
        # asyncio.gather preserves input ordering even when calls complete out of order.
        return list(await asyncio.gather(*tasks))
