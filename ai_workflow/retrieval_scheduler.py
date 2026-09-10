from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar


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

    A private bounded executor is used instead of asyncio's default executor so
    returning from a timed-out scheduler call does not wait for unrelated worker
    shutdown. Python cannot forcibly terminate arbitrary code already running in
    a thread; command providers therefore retain their process-level timeout as
    the hard stop for resource cleanup.
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

        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(deadline_seconds)
        executor = ThreadPoolExecutor(max_workers=self.max_concurrency, thread_name_prefix="ai-workflow-retrieval")

        async def execute(call: ScheduledCall[T]) -> SchedulerOutcome[T]:
            started = time.perf_counter()
            try:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                future = loop.run_in_executor(executor, call.fn)
                value = await asyncio.wait_for(future, timeout=remaining)
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
            except Exception as exc:  # noqa: BLE001 - provider failures are deliberately isolated
                return SchedulerOutcome(
                    label=call.label,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                    error_kind="exception",
                )

        tasks = [asyncio.create_task(execute(call)) for call in calls]
        try:
            # asyncio.gather preserves input order even when calls finish out of order.
            return list(await asyncio.gather(*tasks))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
