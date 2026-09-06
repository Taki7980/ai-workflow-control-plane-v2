# 2026 Adaptive Retrieval Research Notes

These notes record research used to shape V2.1. They are design inputs, not claims that this project reproduces the papers' results.

## Repository/code retrieval

### CORE-Bench — arXiv:2606.11864
https://arxiv.org/abs/2606.11864

A large benchmark for code retrieval in agentic coding settings. The key design implication is that repository-level retrieval should be measured on broader-context tasks rather than only exact snippet/symbol search. V2.1 therefore expands its benchmark categories and keeps structural retrieval separate from ordinary lexical lookup.

## Adaptive retrieval/reranking

### Adaptive Query Routing — arXiv:2604.14222
https://arxiv.org/abs/2604.14222

Reports that retrieval paradigms have different strengths across query/document conditions. This supports routing by query intent rather than forcing every task through one fixed retrieval stack.

### Adaptive Re-Ranking — arXiv:2606.25249
https://arxiv.org/abs/2606.25249

Studies per-query selection between inexpensive sparse retrieval and more expensive reranking paths. The V2.1 analogue is a hard budget plus an evidence-sufficiency gate: expensive providers are only attempted when cheaper evidence is not sufficient.

### MoR: Mixture of Sparse, Dense, and Human Retrievers — arXiv:2506.15862
https://arxiv.org/abs/2506.15862

Motivates treating sparse and dense retrievers as complementary rather than assuming one universally replaces the other. V2.1 therefore retains code-aware BM25 and adds optional semantic/external retriever providers, combining heterogeneous rankings with RRF when needed.

## Fusion and diversity

### Hybrid Retrieval with Rank Fusion and Diversity Reranking — arXiv:2604.13728
https://arxiv.org/abs/2604.13728

Provides a recent empirical example where sparse+dense RRF can outperform either alone, while MMR creates an explicit relevance/diversity trade-off. V2.1 keeps MMR as a post-fusion diversification step rather than treating it as a semantic retriever.

## Confidence and context filtering

### Towards Dependable RAG Using Factual Confidence Prediction — arXiv:2605.05244
https://arxiv.org/abs/2605.05244

Uses conformal prediction in a retrieval/factuality pipeline and highlights that statistical guarantees depend on assumptions such as exchangeability. V2.1 deliberately labels its current sufficiency score as a heuristic, not a calibrated probability.

### Principled Context Engineering for RAG — arXiv:2511.17908
https://arxiv.org/abs/2511.17908

Studies coverage-controlled context filtering via conformal prediction. This is a promising future direction once AI Workflow has a substantially larger, representative labeled retrieval corpus. It is not implemented as a fake guarantee on top of the current small benchmark.

## Online routing / feedback

### Adaptive LLM Routing under Budget Constraints — arXiv:2508.21141
https://arxiv.org/abs/2508.21141

Frames routing as a contextual-bandit problem with cost constraints. V2.1 borrows only the high-level lesson that outcome feedback can improve routing. The implementation remains conservative: telemetry can produce advisory policy recommendations after a minimum sample count, but it never self-modifies deterministic high-risk routing.

## Design decisions resulting from the research

1. Keep code-aware lexical retrieval for exact identifiers and paths.
2. Add semantic retrieval as an optional specialist, not a mandatory replacement.
3. Route structural questions directly toward graph evidence when available.
4. Fuse heterogeneous rankings with RRF; use MMR only for diversity after relevance evidence exists.
5. Use lane budgets as hard ceilings and sufficiency as an escalation/early-stop signal.
6. Do not describe heuristic sufficiency as calibrated confidence.
7. Collect broader benchmark and telemetry data before attempting learned or bandit routing.
8. Keep learned/online mechanisms outside deterministic safety escalation.
