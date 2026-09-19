from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .benchmark_regression import latency_percentiles
from .code_review_graph import (
    graph_freshness,
    repository_data_dir,
    sync_workspace_graphs,
)
from .config import estimate_tokens
from .context_broker import crg_context


SEMANTIC_BENCHMARK_SCHEMA = 1


class CrgSemanticBenchmarkError(RuntimeError):
    pass


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise CrgSemanticBenchmarkError(
            f"git {' '.join(args)} failed: "
            + (proc.stderr.strip() or proc.stdout.strip())
        )
    return proc.stdout.strip()


def _init_repository(repo: Path) -> None:
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "benchmark@example.invalid")
    _run_git(repo, "config", "user.name", "CRG Semantic Benchmark")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "semantic benchmark fixture")


def _copy_fixture(fixture: Path, destination: Path) -> Path:
    repo = destination / "repo"
    shutil.copytree(fixture, repo)
    _init_repository(repo)
    return repo


def _rows_from_items(items: Iterable[Any]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    texts: list[str] = []
    for item in items:
        text = str(getattr(item, "text", ""))
        if not text:
            continue
        texts.append(text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        raw_rows = payload.get("results")
        if not isinstance(raw_rows, list):
            raw_rows = payload.get("impacted_nodes")
        if not isinstance(raw_rows, list):
            raw_rows = []
        rows.extend(row for row in raw_rows if isinstance(row, dict))
    return rows, estimate_tokens("\n".join(texts))


def _row_text(row: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(row),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).casefold()


def _matches_gold(row: Mapping[str, Any], gold: Mapping[str, Any]) -> bool:
    raw = _row_text(row)
    path_contains = str(gold.get("path_contains") or "").strip().casefold()
    name_contains = str(gold.get("name_contains") or "").strip().casefold()
    if path_contains and path_contains not in raw:
        return False
    if name_contains and name_contains not in raw:
        return False
    return bool(path_contains or name_contains)


def score_ranked_rows(
    rows: list[dict[str, Any]],
    gold: list[dict[str, Any]],
) -> dict[str, Any]:
    if not gold:
        raise ValueError("semantic benchmark case must contain gold labels")

    matched_gold: set[int] = set()
    relevant_rows = 0
    first_relevant: int | None = None

    for rank, row in enumerate(rows, 1):
        row_matches = [
            index
            for index, expected in enumerate(gold)
            if _matches_gold(row, expected)
        ]
        if not row_matches:
            continue
        relevant_rows += 1
        if first_relevant is None:
            first_relevant = rank
        matched_gold.update(row_matches)

    precision = relevant_rows / len(rows) if rows else 0.0
    recall = len(matched_gold) / len(gold)
    return {
        "returned": len(rows),
        "gold": len(gold),
        "matched_gold": len(matched_gold),
        "precision_at_k": round(precision, 4),
        "recall_at_k": round(recall, 4),
        "mrr": round(1.0 / first_relevant, 4) if first_relevant else 0.0,
        "full_recall": recall == 1.0,
    }


def validate_cases(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if int(payload.get("schema_version", 0) or 0) != SEMANTIC_BENCHMARK_SCHEMA:
        raise ValueError("unsupported CRG semantic benchmark schema")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("CRG semantic benchmark must contain cases")

    required = {"case_id", "category", "language", "pattern", "target", "query", "gold"}
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("CRG semantic benchmark case must be an object")
        missing = sorted(key for key in required if not raw.get(key))
        if missing:
            raise ValueError(
                f"CRG semantic benchmark case missing: {', '.join(missing)}"
            )
        case_id = str(raw["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate CRG semantic case_id: {case_id}")
        seen.add(case_id)
        gold = raw["gold"]
        if not isinstance(gold, list) or not gold or not all(
            isinstance(item, dict) for item in gold
        ):
            raise ValueError(f"case {case_id} must contain gold objects")
        cases.append(dict(raw))
    return cases


def _query_case(repo: Path, case: Mapping[str, Any], limit: int) -> dict[str, Any]:
    start = time.perf_counter()
    items = crg_context(
        repo,
        str(case["query"]),
        str(case["target"]),
        None,
        limit,
        patterns=(str(case["pattern"]),),
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    rows, tokens = _rows_from_items(items)
    metrics = score_ranked_rows(rows[:limit], list(case["gold"]))
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "language": case["language"],
        "pattern": case["pattern"],
        "target": case["target"],
        "latency_ms": round(elapsed_ms, 2),
        "estimated_context_tokens": tokens,
        "metrics": metrics,
        "rows": rows[:limit],
    }


def _contains_gold(rows: list[dict[str, Any]], *, path: str, name: str) -> bool:
    return any(
        _matches_gold(
            row,
            {"path_contains": path, "name_contains": name},
        )
        for row in rows
    )


def _stale_graph_control(fixture: Path, root: Path) -> dict[str, Any]:
    repo = _copy_fixture(fixture, root / "stale")
    sync = sync_workspace_graphs(repo, {}, timeout=180)
    if sync.get("ready") != 1:
        return {"passed": False, "reason": "initial graph build failed", "sync": sync}

    target = repo / "python" / "payments.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# stale mutation\n",
        encoding="utf-8",
    )
    freshness = graph_freshness(repo, repo)
    items = crg_context(
        repo,
        "Who calls execute_payment?",
        "execute_payment",
        None,
        10,
        patterns=("callers_of",),
    )
    return {
        "passed": not freshness.get("fresh") and items == [],
        "freshness": freshness,
        "returned_items": len(items),
    }


def _rename_delete_control(fixture: Path, root: Path) -> dict[str, Any]:
    repo = _copy_fixture(fixture, root / "rename")
    initial = sync_workspace_graphs(repo, {}, timeout=180)
    if initial.get("ready") != 1:
        return {"passed": False, "reason": "initial graph build failed"}

    payments = repo / "python" / "payments.py"
    consumer = repo / "python" / "alias_consumer.py"
    payments.write_text(
        payments.read_text(encoding="utf-8").replace(
            "execute_payment",
            "execute_payment_v2",
        ),
        encoding="utf-8",
    )
    consumer.write_text(
        consumer.read_text(encoding="utf-8").replace(
            "execute_payment",
            "execute_payment_v2",
        ),
        encoding="utf-8",
    )
    updated = sync_workspace_graphs(repo, {}, timeout=180)
    if updated.get("ready") != 1:
        return {"passed": False, "reason": "graph update failed", "sync": updated}

    old_items = crg_context(
        repo,
        "Who calls execute_payment?",
        "execute_payment",
        None,
        10,
        patterns=("callers_of",),
    )
    new_items = crg_context(
        repo,
        "Who calls execute_payment_v2?",
        "execute_payment_v2",
        None,
        10,
        patterns=("callers_of",),
    )
    old_rows, _ = _rows_from_items(old_items)
    new_rows, _ = _rows_from_items(new_items)
    old_has_consumer = _contains_gold(
        old_rows,
        path="python/alias_consumer.py",
        name="process_order",
    )
    new_has_consumer = _contains_gold(
        new_rows,
        path="python/alias_consumer.py",
        name="process_order",
    )
    return {
        "passed": (not old_has_consumer) and new_has_consumer,
        "old_result_count": len(old_rows),
        "new_result_count": len(new_rows),
    }


def _worktree_control(fixture: Path, root: Path) -> dict[str, Any]:
    repo = _copy_fixture(fixture, root / "worktree-source")
    main_sync = sync_workspace_graphs(repo, {}, timeout=180)
    if main_sync.get("ready") != 1:
        return {"passed": False, "reason": "main graph build failed"}

    worktree = root / "linked-worktree"
    _run_git(repo, "worktree", "add", "-b", "semantic-worktree", str(worktree))
    worktree_sync = sync_workspace_graphs(worktree, {}, timeout=180)
    if worktree_sync.get("ready") != 1:
        return {"passed": False, "reason": "worktree graph build failed"}

    main_dir = repository_data_dir(repo, repo)
    worktree_dir = repository_data_dir(worktree, worktree)
    main_rows, _ = _rows_from_items(
        crg_context(
            repo,
            "Who calls execute_payment?",
            "execute_payment",
            None,
            10,
            patterns=("callers_of",),
        )
    )
    worktree_rows, _ = _rows_from_items(
        crg_context(
            worktree,
            "Who calls execute_payment?",
            "execute_payment",
            None,
            10,
            patterns=("callers_of",),
        )
    )
    main_ok = _contains_gold(
        main_rows,
        path="python/alias_consumer.py",
        name="process_order",
    )
    worktree_ok = _contains_gold(
        worktree_rows,
        path="python/alias_consumer.py",
        name="process_order",
    )
    return {
        "passed": main_ok and worktree_ok and main_dir != worktree_dir,
        "main_data_dir": str(main_dir),
        "worktree_data_dir": str(worktree_dir),
        "main_result_count": len(main_rows),
        "worktree_result_count": len(worktree_rows),
    }


def _write_small_repo(root: Path, caller: str) -> Path:
    root.mkdir(parents=True)
    (root / ".gitignore").write_text("ai-workspace/\n", encoding="utf-8")
    (root / "shared.py").write_text(
        "def shared() -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )
    (root / "consumer.py").write_text(
        "from shared import shared\n\n"
        f"def {caller}() -> str:\n"
        "    return shared()\n",
        encoding="utf-8",
    )
    _init_repository(root)
    return root


def _multi_repo_control(root: Path) -> dict[str, Any]:
    repo_a = _write_small_repo(root / "multi-a", "call_a")
    repo_b = _write_small_repo(root / "multi-b", "call_b")
    a_sync = sync_workspace_graphs(repo_a, {}, timeout=180)
    b_sync = sync_workspace_graphs(repo_b, {}, timeout=180)
    if a_sync.get("ready") != 1 or b_sync.get("ready") != 1:
        return {"passed": False, "reason": "multi-repo graph build failed"}

    a_rows, _ = _rows_from_items(
        crg_context(
            repo_a,
            "Who calls shared?",
            "shared",
            None,
            10,
            patterns=("callers_of",),
        )
    )
    b_rows, _ = _rows_from_items(
        crg_context(
            repo_b,
            "Who calls shared?",
            "shared",
            None,
            10,
            patterns=("callers_of",),
        )
    )
    a_text = "\n".join(_row_text(row) for row in a_rows)
    b_text = "\n".join(_row_text(row) for row in b_rows)
    return {
        "passed": (
            "call_a" in a_text
            and "call_b" not in a_text
            and "call_b" in b_text
            and "call_a" not in b_text
        ),
        "repo_a_results": a_rows,
        "repo_b_results": b_rows,
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(row[key])
        for row in rows
        if row.get(key) is not None
    ]
    return round(statistics.mean(values), 4) if values else None


def run_crg_semantic_benchmark(
    *,
    fixture: Path,
    cases_path: Path,
    limit: int = 20,
) -> dict[str, Any]:
    if shutil.which("code-review-graph") is None:
        raise CrgSemanticBenchmarkError("code-review-graph is not installed")
    if shutil.which("git") is None:
        raise CrgSemanticBenchmarkError("git is not installed")

    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = validate_cases(payload)

    with tempfile.TemporaryDirectory(prefix="crg-semantic-") as td:
        scratch = Path(td)
        repo = _copy_fixture(fixture, scratch / "semantic")
        sync = sync_workspace_graphs(repo, {}, timeout=180)
        if sync.get("ready") != 1:
            raise CrgSemanticBenchmarkError(
                "semantic fixture graph build failed: "
                + json.dumps(sync, sort_keys=True)
            )

        rows = [_query_case(repo, case, limit) for case in cases]
        controls = {
            "stale_graph": _stale_graph_control(
                fixture,
                scratch / "control-stale",
            ),
            "rename_delete": _rename_delete_control(
                fixture,
                scratch / "control-rename",
            ),
            "worktree": _worktree_control(
                fixture,
                scratch / "control-worktree",
            ),
            "multi_repo": _multi_repo_control(
                scratch / "control-multi",
            ),
        }

    metric_rows = [row["metrics"] for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows]
    token_values = [int(row["estimated_context_tokens"]) for row in rows]
    control_values = [bool(value.get("passed")) for value in controls.values()]

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[str(row["category"])].append(row)

    category_summary = {
        category: {
            "cases": len(group),
            "mean_precision_at_k": _mean(
                [item["metrics"] for item in group],
                "precision_at_k",
            ),
            "mean_recall_at_k": _mean(
                [item["metrics"] for item in group],
                "recall_at_k",
            ),
            "mean_mrr": _mean(
                [item["metrics"] for item in group],
                "mrr",
            ),
            "full_recall_rate": round(
                sum(bool(item["metrics"]["full_recall"]) for item in group)
                / len(group),
                4,
            ),
        }
        for category, group in sorted(by_category.items())
    }

    return {
        "schema_version": 1,
        "benchmark": str(payload.get("name") or "crg-semantic-golden"),
        "crg_version_expected": payload.get("crg_version"),
        "cases": rows,
        "controls": controls,
        "by_category": category_summary,
        "summary": {
            "cases": len(rows),
            "mean_precision_at_k": _mean(metric_rows, "precision_at_k"),
            "mean_recall_at_k": _mean(metric_rows, "recall_at_k"),
            "mean_mrr": _mean(metric_rows, "mrr"),
            "full_recall_rate": round(
                sum(bool(row["metrics"]["full_recall"]) for row in rows)
                / len(rows),
                4,
            ),
            "mean_latency_ms": (
                round(statistics.mean(latencies), 2) if latencies else None
            ),
            "latency_p50_ms": latency_percentiles(latencies)["p50"],
            "latency_p95_ms": latency_percentiles(latencies)["p95"],
            "latency_p99_ms": latency_percentiles(latencies)["p99"],
            "mean_estimated_context_tokens": (
                round(statistics.mean(token_values), 2)
                if token_values
                else None
            ),
            "lifecycle_pass_rate": round(
                sum(control_values) / len(control_values),
                4,
            ),
            "stale_graph_block_rate": (
                1.0 if controls["stale_graph"].get("passed") else 0.0
            ),
        },
        "notes": [
            "Gold labels are semantic fixture expectations, not text-similarity labels.",
            "Latency is local wall-clock query latency on the benchmark runner.",
            "Estimated context tokens use the control plane estimator, not billed tokens.",
            "SCIP/source differential validation is intentionally deferred to PR-22.",
        ],
    }
