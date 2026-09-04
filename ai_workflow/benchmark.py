from __future__ import annotations
import json, math, statistics, time
from pathlib import Path
from .budget import budget_for
from .classifier import classify
from .config import estimate_tokens
from .context_broker import gather
from .providers import detect, execution_provider, model_tier


def retrieval_metrics(items: list, relevant_patterns: list[str], k: int = 5) -> dict | None:
    """Compute binary retrieval metrics from explicit gold text patterns."""
    patterns = [pattern.casefold() for pattern in relevant_patterns if pattern.strip()]
    if not patterns:
        return None
    cutoff = max(1, int(k))
    ranked = items[:cutoff]
    texts = [item.text.casefold() for item in ranked]
    relevance = [int(any(pattern in text for pattern in patterns)) for text in texts]
    first_relevant = next((rank for rank, value in enumerate(relevance, 1) if value), None)

    # Gold patterns are relevance units. Count each once at its earliest supporting
    # item; multiple patterns in one item occupy consecutive idealized positions.
    unmatched = set(range(len(patterns)))
    next_position = 1
    dcg = 0.0
    for item_rank, text in enumerate(texts, 1):
        matched = [index for index in sorted(unmatched) if patterns[index] in text]
        for index in matched:
            position = max(item_rank, next_position)
            dcg += 1.0 / math.log2(position + 1)
            next_position = position + 1
            unmatched.remove(index)
    covered = len(patterns) - len(unmatched)
    ideal_dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, len(patterns) + 1)
    )
    return {
        "k": cutoff,
        "relevant_items": sum(relevance),
        "precision_at_k": sum(relevance) / cutoff,
        "recall_at_k": covered / len(patterns),
        "mrr": 1.0 / first_relevant if first_relevant else 0.0,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0,
    }


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
        row = {
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
        }
        expected_lane = case.get('expected_lane')
        if expected_lane:
            row['lane_correct'] = decision.lane.value == expected_lane
        metrics = retrieval_metrics(
            items,
            case.get('relevant_context') or [],
            int(case.get('retrieval_k', 5)),
        )
        if metrics:
            row['retrieval'] = metrics
        rows.append(row)

    lane_rows = [row for row in rows if 'lane_correct' in row]
    retrieval_rows = [row['retrieval'] for row in rows if 'retrieval' in row]
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
            'labeled_lane_cases': len(lane_rows),
            'lane_accuracy': round(sum(row['lane_correct'] for row in lane_rows) / len(lane_rows), 4) if lane_rows else None,
            'labeled_retrieval_cases': len(retrieval_rows),
            'mean_precision_at_k': round(statistics.mean(row['precision_at_k'] for row in retrieval_rows), 4) if retrieval_rows else None,
            'mean_recall_at_k': round(statistics.mean(row['recall_at_k'] for row in retrieval_rows), 4) if retrieval_rows else None,
            'mean_mrr': round(statistics.mean(row['mrr'] for row in retrieval_rows), 4) if retrieval_rows else None,
            'mean_ndcg_at_k': round(statistics.mean(row['ndcg_at_k'] for row in retrieval_rows), 4) if retrieval_rows else None,
        },
    }


def load_tasks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('benchmark task file must be a JSON array')
    return [x for x in data if isinstance(x, dict)]
