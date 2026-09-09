# Concurrent retrieval engine

`WorkflowEngine` is the application-level retrieval sequencer. It keeps the existing synchronous broker API while adding an async API and bounded concurrency for independent workspace roots and specialist retrievers.

## Configuration

The scheduler is optional. Existing version-2 configurations do not need to be changed.

```json
{
  "execution": {
    "retrieval_scheduler": {
      "max_concurrency": 4,
      "global_deadline_seconds": 12.0
    }
  }
}
```

When the section is absent, the same values are used as safe runtime defaults.

`max_concurrency` limits the private thread pool used to call blocking retrieval adapters. `global_deadline_seconds` covers the whole broker retrieval operation, including initial workspace-root retrieval and any later semantic/external escalation.

## Determinism

Concurrency changes when providers execute, not how their results are merged. Scheduled outcomes are returned in their original provider/root order, so the existing ranking, sufficiency, selector, and orchestration logic receives deterministic input for identical provider results.

The public compatibility functions remain:

```python
from ai_workflow.adaptive_broker import gather, gather_detailed
```

Async callers can use:

```python
from ai_workflow.adaptive_broker import gather_detailed_async
```

or instantiate `WorkflowEngine` directly.

## Deadlines and cancellation

A private bounded `ThreadPoolExecutor` prevents `asyncio.run()` from draining timed-out retrieval workers before returning to the caller. Once the global deadline is reached, unfinished calls are reported as `deadline` failures and are excluded from the result set.

Python cannot safely kill arbitrary code that is already executing in a worker thread. Therefore:

- the global deadline is a caller-latency boundary;
- configured command providers still enforce their process-level timeout/output limits as the hard resource boundary;
- custom in-process retrievers should implement their own bounded I/O and cancellation behavior.

Scheduler deadline information is exposed in `diagnostics.scheduler`, while provider/scheduler failures continue to appear in `diagnostics.provider_errors` and `fallbacks`.

## Scope

The engine deliberately does not introduce distributed workers, a daemon, or a third-party async framework. The research plan recommends proving local bounded concurrency first and only adding a daemon/hot cache when profiling demonstrates material benefit.