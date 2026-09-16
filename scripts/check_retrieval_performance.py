from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workflow.math_retrieval import BM25Scorer, tokenize  # noqa: E402


VOCAB = (
    "payment",
    "retry",
    "invoice",
    "authorization",
    "session",
    "cache",
    "repository",
    "graph",
    "context",
    "token",
    "selector",
    "benchmark",
    "latency",
    "provider",
    "workflow",
    "mutation",
    "structural",
    "semantic",
    "index",
    "freshness",
)


def _documents(count: int) -> list[str]:
    docs: list[str] = []
    width = len(VOCAB)
    for doc_index in range(count):
        length = 48 + (doc_index % 19)
        terms = [
            VOCAB[(doc_index * 7 + offset * 5) % width]
            for offset in range(length)
        ]
        repeated = VOCAB[doc_index % width]
        terms.extend([repeated] * (1 + doc_index % 5))
        docs.append(" ".join(terms))
    return docs


def _queries(count: int) -> list[str]:
    width = len(VOCAB)
    return [
        " ".join(
            (
                VOCAB[(index * 3) % width],
                VOCAB[(index * 3 + 7) % width],
                VOCAB[(index * 3 + 13) % width],
            )
        )
        for index in range(count)
    ]


def _reference_rankings(
    texts: list[str],
    queries: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[list[tuple[float, int]]]:
    token_docs = [tokenize(text) for text in texts]
    token_sets = [set(tokens) for tokens in token_docs]
    doc_freqs: dict[str, int] = {}
    for token_set in token_sets:
        for token in token_set:
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    num_docs = len(token_docs)
    avgdl = sum(len(tokens) for tokens in token_docs) / max(1, num_docs)
    idf = {
        token: max(
            0.01,
            math.log(
                1 + (num_docs - freq + 0.5) / (freq + 0.5)
            ),
        )
        for token, freq in doc_freqs.items()
    }

    rankings: list[list[tuple[float, int]]] = []
    for query in queries:
        query_tokens = list(set(tokenize(query)))
        rows: list[tuple[float, int]] = []
        for doc_id, tokens in enumerate(token_docs):
            if avgdl <= 0:
                continue
            doc_len = len(tokens)
            len_norm = 1.0 - b + b * (doc_len / avgdl)
            term_freq: dict[str, int] = {}
            for term in query_tokens:
                if term in token_sets[doc_id]:
                    term_freq[term] = tokens.count(term)
            score = 0.0
            for term in query_tokens:
                if term not in term_freq:
                    continue
                freq = term_freq[term]
                numerator = freq * (k1 + 1)
                denominator = freq + k1 * len_norm
                score += idf.get(term, 0.01) * (numerator / denominator)
            if score > 0:
                rows.append((score, doc_id))
        rows.sort(key=lambda row: -row[0])
        rankings.append(rows)
    return rankings


def _optimized_rankings(
    texts: list[str],
    queries: list[str],
) -> list[list[tuple[float, int]]]:
    scorer = BM25Scorer()
    scorer.fit(texts, list(range(len(texts))))
    return [scorer.rank(query) for query in queries]


def _compare(
    reference: list[list[tuple[float, int]]],
    optimized: list[list[tuple[float, int]]],
) -> tuple[bool, float]:
    parity = len(reference) == len(optimized)
    max_delta = 0.0
    if not parity:
        return False, float("inf")

    for reference_rows, optimized_rows in zip(reference, optimized, strict=True):
        if len(reference_rows) != len(optimized_rows):
            parity = False
            continue
        reference_ids = [doc_id for _, doc_id in reference_rows]
        optimized_ids = [doc_id for _, doc_id in optimized_rows]
        if reference_ids != optimized_ids:
            parity = False
        for (reference_score, reference_id), (
            optimized_score,
            optimized_id,
        ) in zip(reference_rows, optimized_rows, strict=True):
            if reference_id != optimized_id:
                continue
            max_delta = max(
                max_delta,
                abs(reference_score - optimized_score),
            )
    return parity, max_delta


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare optimized BM25 with the pre-optimization reference "
            "while reporting timing as non-blocking evidence."
        )
    )
    parser.add_argument("--documents", type=int, default=800)
    parser.add_argument("--queries", type=int, default=40)
    args = parser.parse_args()
    if args.documents <= 0 or args.queries <= 0:
        parser.error("--documents and --queries must be positive")

    texts = _documents(args.documents)
    queries = _queries(args.queries)

    started = time.perf_counter()
    reference = _reference_rankings(texts, queries)
    reference_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    optimized = _optimized_rankings(texts, queries)
    optimized_ms = (time.perf_counter() - started) * 1000

    parity, max_delta = _compare(reference, optimized)
    speedup = (
        reference_ms / optimized_ms
        if optimized_ms > 0
        else None
    )
    payload = {
        "documents": args.documents,
        "queries": args.queries,
        "ranking_parity": parity,
        "max_score_delta": max_delta,
        "reference_elapsed_ms": round(reference_ms, 3),
        "optimized_elapsed_ms": round(optimized_ms, 3),
        "observed_speedup": (
            round(speedup, 4) if speedup is not None else None
        ),
        "timing_is_blocking": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if parity and max_delta <= 1e-12 else 1


if __name__ == "__main__":
    raise SystemExit(main())
