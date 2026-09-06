# Adaptive Retrieval V2.1 Design

## Goal

Evolve the control plane from a fixed retrieval ladder into a deterministic, query-aware retrieval controller that chooses lexical, semantic, structural, or mixed retrieval; stops when evidence is sufficient; preserves hard context ceilings; records provenance and traces; and measures quality with a materially broader benchmark suite.

## Constraints

- Python 3.10+.
- Core package remains dependency-free.
- Source code and tests remain authoritative.
- Semantic retrieval is optional and provider-backed; absence must degrade safely.
- Existing Answer / Small / Full policy and hard high-risk escalation remain authoritative.
- CRG remains the structural provider for callers/callees/tests/impact.
- No LLM is allowed to silently override deterministic safety routing.
- External/destructive writes remain outside retrieval and require explicit approval.

## Retrieval architecture

The broker derives a RetrievalIntent: exact, semantic, structural, or mixed.

- exact: symbol, path, endpoint, identifier-heavy queries -> lightweight index/BM25.
- semantic: natural-language paraphrase/intent queries with weak code identifiers -> optional semantic provider plus lexical evidence.
- structural: callers/callees/dependencies/impact/tests/blast-radius -> CRG directly when ready.
- mixed: combine lexical and semantic candidates and fuse ranks before diversity selection.

The semantic provider contract is command-based to keep the package dependency-free. A configured command receives a JSON request on stdin and returns JSONL/JSON candidates with text, score, and optional provenance metadata. Missing/failing providers are recorded and skipped.

## Evidence sufficiency

After each retrieval stage, the broker computes deterministic sufficiency from exact matches, lexical coverage, source diversity, structural completeness, and top-score evidence. Sufficiency does not prove correctness; it decides whether more retrieval cost is justified. Low sufficiency escalates to another provider or targeted source while never exceeding the lane hard ceiling.

## Adaptive budgets

Lane budgets remain hard maximums. Each retrieval stage gets a soft allowance. Unused allowance is not automatically filled. The broker stops early when evidence is sufficient, reducing context volume without changing safety escalation.

## Provenance and trust

Context items carry provenance metadata where available: path, line/line range, SHA-256, retriever, freshness, trust class, and selection reason. Repository text is always data, never executable instruction. Generated memory/cache content is marked separately from source-controlled code.

## Telemetry

Each non-read-only execution may write a compact JSON trace under `ai-workspace/generated/traces/` containing lane/risk, retrieval intent, attempted/skipped providers, stage latency, candidate/selected counts, sufficiency, budget usage, stale rejections, and fallback reasons. Answer-mode remains side-effect-free unless tracing is explicitly enabled.

## Benchmarking

Expand benchmark cases across exact identifiers, paraphrases, routes, test discovery, structural queries, ambiguity, stale data, and negative/no-result cases. Add grouping by query type and strategy-comparison support. Continue reporting Precision@k, Recall@k, MRR, nDCG, latency, and context usage; add escalation/fallback/sufficiency statistics. Keep a clear warning that retrieval metrics do not prove downstream task correctness.

## CI

Run unit tests as before and add a benchmark regression job that validates benchmark schema, minimum case count, and expected routing/retrieval invariants. Do not gate on external semantic or CRG providers.
