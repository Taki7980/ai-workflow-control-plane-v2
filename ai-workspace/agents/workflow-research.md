# Workflow Research Notes

## Current architecture decision

AI Workflow is an **efficiency control plane**, not a replacement for execution methodologies or code-intelligence engines.

- Superpowers: optional Full-lane execution provider.
- Code Review Graph: optional structural context provider.
- AI Workflow: lane/risk routing, context brokerage, budgets, handoffs, compression, verification, and durable cross-session memory.

## Constraints

- Keep cheap tasks cheap; avoid CRG/subagent overhead when local indexes or targeted source are enough.
- Treat indexes and memories as caches, not source of truth.
- Reject stale file-backed evidence using SHA-256.
- Keep context budgets explicit and loss-aware.
- Measure provider tokens, command-output reduction, wall time, and correctness separately.

## Upstream references checked for v2

- Superpowers subagent-driven development and plan execution: https://github.com/obra/superpowers
- Code Review Graph CLI/MCP and benchmark caveats: https://github.com/tirth8205/code-review-graph

## Retrieval foundation

The local retriever deliberately stays dependency-free until labeled benchmarks justify a dense model.

- **Okapi BM25** ranks lexical evidence with document-length normalization. Implementation follows Robertson and Zaragoza's probabilistic relevance framework; it is not labeled BM25+ because no lower-bound delta term is implemented: https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf
- **Reciprocal Rank Fusion** combines source-provided and lexical ranks without pretending their raw scores share a calibrated scale: https://dl.acm.org/doi/10.1145/1571941.1572114
- **Maximal Marginal Relevance** reduces redundant context after irrelevant candidates are removed. It is a greedy relevance/novelty reranker, not a general optimal submodular solver: https://storage.ghost.io/c/97/88/97889716-a759-46f4-b63f-4f5c46a13333/content/files/~jgc/publication/the_use_mmr_diversity_based_ltmir_1998.pdf
- **CodeRAG-Bench** reports that good retrieved context can improve code generation while retrievers still struggle to fetch useful evidence. This motivates measuring retrieval separately from token volume: https://aclanthology.org/2025.findings-naacl.176/
- **CoRet** reports gains from combining code semantics, repository structure, and call-graph dependencies. This supports the optional CRG tier, but does not justify adding a dense model without a local labeled benchmark: https://aclanthology.org/2025.acl-short.62/
- **Lost in the Middle** shows that merely expanding context can reduce effective use of relevant evidence depending on position. This supports bounded, ranked packets over raw context dumps: https://aclanthology.org/2024.tacl-1.9/
- **RECOMP** shows the value of query-directed compression and selective augmentation, including omitting irrelevant retrieved context. The local deterministic analogue is lazy targeted-source fallback rather than unconditional scanning: https://proceedings.iclr.cc/paper_files/paper/2024/hash/bda88ed2892f5e61c9a9bf215c566913-Abstract-Conference.html

## Evaluation contract

Benchmark cases may label expected lanes and relevant text patterns. The benchmark reports lane accuracy, Precision@k, pattern Recall@k, MRR, and pattern-level nDCG@k. Each gold pattern is counted once at its earliest supporting result; missing patterns reduce ideal-normalized gain. These metrics validate routing and retrieval against those labels only; they do not establish downstream code correctness or provider-token savings.
