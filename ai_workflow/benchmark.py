from __future__ import annotations
import json, math, statistics, time
from collections import defaultdict
from pathlib import Path
from .adaptive_broker import gather_detailed
from .budget import budget_for
from .classifier import classify
from .config import estimate_tokens
from .providers import detect, execution_provider, model_tier


def retrieval_metrics(items: list, relevant_patterns: list[str], k: int = 5) -> dict | None:
    patterns = [pattern.casefold() for pattern in relevant_patterns if pattern.strip()]
    if not patterns:
        return None
    cutoff = max(1, int(k))
    ranked = items[:cutoff]
    texts = [item.text.casefold() for item in ranked]
    relevance = [int(any(pattern in text for pattern in patterns)) for text in texts]
    first_relevant = next((rank for rank, value in enumerate(relevance, 1) if value), None)
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
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, len(patterns) + 1))
    return {
        "k": cutoff,
        "relevant_items": sum(relevance),
        "matched_patterns": covered,
        "relevant_item_density": sum(relevance) / max(1, len(ranked)),
        "precision_at_k": sum(relevance) / cutoff,
        "recall_at_k": covered / len(patterns),
        "mrr": 1.0 / first_relevant if first_relevant else 0.0,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0,
    }


def _mean(rows: list[dict], key: str):
    values = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.mean(values), 4) if values else None


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
        items, retrieval = gather_detailed(
            root, task, decision, budget, config, providers,
            case.get('symbol'), case.get('endpoint'), case.get('changed_files') or [],
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        used = estimate_tokens('\n'.join(i.text for i in items))
        row = {
            'task': task,
            'query_type': case.get('query_type', 'unclassified'),
            'lane': decision.lane.value,
            'risk': decision.risk.value,
            'routing_confidence': decision.confidence,
            'execution_provider': execution_provider(decision.lane, config, providers),
            'model_tier': model_tier(decision, config),
            'retrieval_intent': retrieval['retrieval_intent'],
            'retrieval_sufficient': retrieval['sufficiency']['sufficient'],
            'retrieval_sufficiency_score': retrieval['sufficiency']['score'],
            'evidence_state': retrieval.get('evidence_state'),
            'selector_mode': (retrieval.get('selector') or {}).get('mode'),
            'workspace_fingerprint': (retrieval.get('workspace_state') or {}).get('fingerprint'),
            'orchestration_complexity_score': (retrieval.get('orchestration') or {}).get('complexity_score'),
            'fallbacks': retrieval['fallbacks'],
            'context_sources': list(dict.fromkeys(i.source for i in items)),
            'estimated_context_tokens': used,
            'budget_tokens': budget.estimated_tokens,
            'budget_utilization': round(used / budget.estimated_tokens, 4) if budget.estimated_tokens else 0,
            'elapsed_ms': elapsed_ms,
        }
        expected_lane = case.get('expected_lane')
        if expected_lane:
            row['lane_correct'] = decision.lane.value == expected_lane
        expected_intent = case.get('expected_intent')
        if expected_intent:
            row['intent_correct'] = retrieval['retrieval_intent'] == expected_intent
        expected_evidence = case.get('expected_evidence_state')
        if expected_evidence:
            row['evidence_state_correct'] = retrieval.get('evidence_state') == expected_evidence
        if case.get('no_gold'):
            row['abstention_correct'] = retrieval.get('evidence_state') == 'abstain'
        metrics = retrieval_metrics(items, case.get('relevant_context') or [], int(case.get('retrieval_k', 5)))
        if metrics:
            metrics['matched_patterns_per_1k_tokens'] = round(metrics['matched_patterns'] * 1000 / max(1, used), 4)
            row['retrieval'] = metrics
        rows.append(row)

    lane_rows = [row for row in rows if 'lane_correct' in row]
    intent_rows = [row for row in rows if 'intent_correct' in row]
    evidence_rows = [row for row in rows if 'evidence_state_correct' in row]
    abstention_rows = [row for row in rows if 'abstention_correct' in row]
    retrieval_rows = [row['retrieval'] for row in rows if 'retrieval' in row]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row['query_type']].append(row)
    by_query_type = {}
    for name, group in sorted(groups.items()):
        rr = [r['retrieval'] for r in group if 'retrieval' in r]
        by_query_type[name] = {
            'cases': len(group),
            'lane_accuracy': round(sum(r.get('lane_correct', False) for r in group if 'lane_correct' in r) / max(1, sum('lane_correct' in r for r in group)), 4) if any('lane_correct' in r for r in group) else None,
            'intent_accuracy': round(sum(r.get('intent_correct', False) for r in group if 'intent_correct' in r) / max(1, sum('intent_correct' in r for r in group)), 4) if any('intent_correct' in r for r in group) else None,
            'mean_recall_at_k': _mean(rr, 'recall_at_k'),
            'mean_mrr': _mean(rr, 'mrr'),
            'mean_relevant_item_density': _mean(rr, 'relevant_item_density'),
            'mean_pattern_yield_per_1k_tokens': _mean(rr, 'matched_patterns_per_1k_tokens'),
        }
    return {
        'scope': 'routing-and-context-only',
        'warning': 'Estimated context tokens are not provider-billed tokens. Retrieval metrics measure supplied gold patterns and do not prove downstream task correctness.',
        'providers': providers.to_dict(),
        'cases': rows,
        'by_query_type': by_query_type,
        'summary': {
            'cases': len(rows),
            'mean_estimated_context_tokens': round(statistics.mean([r['estimated_context_tokens'] for r in rows]), 2) if rows else 0,
            'mean_budget_utilization': round(statistics.mean([r['budget_utilization'] for r in rows]), 4) if rows else 0,
            'mean_elapsed_ms': round(statistics.mean([r['elapsed_ms'] for r in rows]), 2) if rows else 0,
            'lane_accuracy': round(sum(row['lane_correct'] for row in lane_rows) / len(lane_rows), 4) if lane_rows else None,
            'intent_accuracy': round(sum(row['intent_correct'] for row in intent_rows) / len(intent_rows), 4) if intent_rows else None,
            'evidence_state_accuracy': round(sum(row['evidence_state_correct'] for row in evidence_rows) / len(evidence_rows), 4) if evidence_rows else None,
            'abstention_accuracy': round(sum(row['abstention_correct'] for row in abstention_rows) / len(abstention_rows), 4) if abstention_rows else None,
            'mean_precision_at_k': _mean(retrieval_rows, 'precision_at_k'),
            'mean_recall_at_k': _mean(retrieval_rows, 'recall_at_k'),
            'mean_mrr': _mean(retrieval_rows, 'mrr'),
            'mean_ndcg_at_k': _mean(retrieval_rows, 'ndcg_at_k'),
            'mean_relevant_item_density': _mean(retrieval_rows, 'relevant_item_density'),
            'mean_pattern_yield_per_1k_tokens': _mean(retrieval_rows, 'matched_patterns_per_1k_tokens'),
            'sufficiency_rate': round(sum(bool(r['retrieval_sufficient']) for r in rows) / len(rows), 4) if rows else 0,
            'fallback_rate': round(sum(bool(r['fallbacks']) for r in rows) / len(rows), 4) if rows else 0,
        },
    }


def load_tasks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('benchmark task file must be a JSON array')
    return [x for x in data if isinstance(x, dict)]
