from __future__ import annotations
import json, statistics, time
from pathlib import Path
from .budget import budget_for
from .classifier import classify
from .config import estimate_tokens
from .context_broker import gather
from .providers import detect, execution_provider, model_tier


def run_benchmark(root: Path, config: dict, tasks: list[dict]) -> dict:
    providers = detect(root, config)
    rows = []
    for case in tasks:
        task = str(case.get('task', '')).strip()
        if not task:
            continue
        start = time.perf_counter()
        decision = classify(task, config)
        budget = budget_for(decision.lane, config)
        items = gather(
            root, task, decision, budget, config, providers,
            case.get('symbol'), case.get('endpoint'), case.get('changed_files') or [],
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        used = estimate_tokens('\n'.join(i.text for i in items))
        rows.append({
            'task': task,
            'lane': decision.lane.value,
            'risk': decision.risk.value,
            'execution_provider': execution_provider(decision.lane, config, providers),
            'model_tier': model_tier(decision, config),
            'context_sources': list(dict.fromkeys(i.source for i in items)),
            'estimated_context_tokens': used,
            'budget_tokens': budget.estimated_tokens,
            'budget_utilization': round(used / budget.estimated_tokens, 4) if budget.estimated_tokens else 0,
            'elapsed_ms': elapsed_ms,
        })
    return {
        'scope': 'routing-and-context-only',
        'warning': 'Estimated context tokens are not provider-billed tokens and this benchmark does not measure task correctness.',
        'providers': providers.to_dict(),
        'cases': rows,
        'summary': {
            'cases': len(rows),
            'mean_estimated_context_tokens': round(statistics.mean([r['estimated_context_tokens'] for r in rows]), 2) if rows else 0,
            'mean_budget_utilization': round(statistics.mean([r['budget_utilization'] for r in rows]), 4) if rows else 0,
            'mean_elapsed_ms': round(statistics.mean([r['elapsed_ms'] for r in rows]), 2) if rows else 0,
        },
    }


def load_tasks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('benchmark task file must be a JSON array')
    return [x for x in data if isinstance(x, dict)]
