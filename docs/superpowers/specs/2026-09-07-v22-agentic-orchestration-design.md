# V2.2 Agentic Orchestration Design

## Goal

Make AI Workflow a deterministic control plane that coordinates **Superpowers** for software-development process and **Code Review Graph (CRG)** for structural code intelligence, while improving context assembly with mathematically budgeted selection and explicit evidence-state contracts.

## Research basis — 2026-09-07

The design is grounded in current repository-retrieval and agent-orchestration research:

- **PACMS (2026)** formulates prompt assembly as budget-constrained monotone submodular facility location. Given candidate pool `C`, budget `B`, mandatory set `M`, relevance `rel(i,q)` and coverage weights `w_ij`, select `S` maximizing `F(S)=sum_i max_{j in S} w_ij` subject to cost and mandatory constraints. It reports that pure relevance can be preferable under very tight budgets, while coverage-based selection is stronger as redundancy and budget increase.
- **RGAO (2026)** conditions multi-agent topology on a structural-complexity vector retrieved from the codebase and composes per-agent resource budgets under a conserved parent budget.
- **Agent Retrieval Bench (2026)** shows no single retriever dominates across code2test/comment2context/trace2code/edit2ripple and highlights natural no-gold calibration failures. The control plane therefore needs an explicit abstention/exploration state instead of forcing a context packet.
- **ContextBench (2026)** finds coding agents tend to favor recall over precision and exposes a gap between explored and actually used context. V2.2 therefore measures density/yield as well as recall.
- **SWE Context Bench (2026)** shows correct summarized experience helps while unfiltered/incorrect experience can hurt. Durable memory remains provenance/freshness gated and participates in the same assembly selector as other context.
- **StagedWorkspace (2026)** motivates a workspace-state contract tying parsed views and edits to concrete versions/content hashes.
- **Superpowers v6.3.0 (2026-08-12)** adds Hermes support and task-scaled brainstorming; v6.2.0 scopes SDD scratch state per plan. V2.2 emits plan-scoped skill contracts rather than hard-coding obsolete reviewer internals.

## Architecture

```text
Task
  -> deterministic lane/risk
  -> retrieval intent
  -> workspace snapshot fingerprint
  -> base + semantic + external + CRG evidence
  -> RRF candidate fusion
  -> evidence state: sufficient | requires_exploration | abstain
  -> budgeted context assembly
       tight budget -> relevance-first
       normal budget -> submodular facility-location greedy
       fallback -> existing MMR
  -> structural complexity vector
  -> conserved orchestration budget
  -> Superpowers contract
       Answer -> direct
       Small -> TDD -> verification
       Full -> writing-plans -> SDD (or executing-plans fallback) -> review -> verification
       High-risk Full -> stronger CRG impact/test evidence + same Superpowers gates
  -> execute
```

## 1. Budgeted context assembly

### Candidate utility

The core remains dependency-free. When dense embeddings are unavailable, use normalized lexical/source relevance and token-set similarity rather than pretending lexical similarity is embedding cosine.

For candidates `i,j` and query `q`:

- `r_i in [0,1]`: normalized candidate relevance from fused/source rank and lexical query overlap.
- `sim(i,j) in [0,1]`: Jaccard similarity over code-aware tokens.
- `w_ij = r_i * sim(i,j)`.
- `F(S) = sum_i max_{j in S} w_ij`.

Selection uses CELF-style lazy greedy on marginal-gain-per-character under `B`, while mandatory exact/structural evidence is inserted first. If `B / total_candidate_chars <= tight_budget_fraction`, relevance-first selection is used because PACMS reports a tight-budget regime where top-k is difficult to beat.

This is a deterministic approximation of the PACMS objective using information available in the dependency-free core. It does **not** claim embedding-equivalent semantics.

## 2. Evidence state

Every retrieval returns one of:

- `sufficient`: evidence satisfies the current task intent.
- `requires_exploration`: mutation/structural task lacks enough evidence; agents may investigate but must not edit yet.
- `abstain`: read-only query has no trustworthy repository evidence; do not fabricate a repository-grounded answer.

The state is derived from existing sufficiency signals plus intent/lane. High-risk mutation rules remain deterministic and cannot be downgraded.

## 3. CRG -> Superpowers orchestration contract

CRG is structural intelligence; Superpowers is process orchestration. V2.2 keeps those roles separate.

A structural-complexity vector records deterministic signals:

`[lane_weight, risk_weight, changed_file_count, workspace_root_count, structural_intent, evidence_gap]`.

The contract maps those signals into:

- ordered CRG tool/CLI plan,
- Superpowers skill sequence,
- maximum CRG calls,
- maximum graph depth,
- context-character ceiling,
- maximum parallel agent slots,
- review passes,
- verification passes.

Child budgets must not exceed the parent component-wise budget. The contract is descriptive and enforceable by callers; it does not invoke hidden Superpowers internals.

### CRG tool plan

For CRG MCP-capable harnesses, emit a compact ordered plan:

1. `get_minimal_context_tool` first.
2. Structural/mutation work: `get_impact_radius_tool` or `query_graph_tool` / `traverse_graph_tool` as required.
3. Tests: graph `tests_for` evidence.
4. Review: `get_review_context_tool` at minimal detail.

Standalone CLI keeps the existing supported `query`, `impact`, and `search` fallback.

## 4. Workspace-state contract

A stable workspace fingerprint hashes:

- resolved workspace root,
- Git HEAD when available,
- changed-file identities/content hashes,
- local index-state digest.

The fingerprint is emitted in context diagnostics and provenance. A downstream agent can reject a packet built against a different workspace state.

## 5. Benchmark extensions

Add no-gold and counterfactual controls and report:

- abstention accuracy,
- evidence-state accuracy,
- relevant-pattern yield per 1k estimated tokens,
- relevant-pattern density,
- existing P@k/R@k/MRR/nDCG,
- budget utilization and latency.

These are retrieval/control-plane metrics only; they do not prove patch correctness.

## 6. Failure behavior

- Missing CRG -> bounded source/semantic fallback and `requires_exploration` when mutation evidence remains weak.
- Missing Superpowers -> native Plan/Build/Review fallback, preserving verification gates.
- Selector failure -> existing RRF/MMR path.
- Missing Git -> workspace fingerprint still includes root/index/changed-file hashes.
- No-gold read-only query -> `abstain`, not hallucinated repository context.

## Non-goals

- No self-modifying learned router.
- No mandatory embedding dependency.
- No reimplementation of CRG's graph database.
- No reimplementation of Superpowers' internal task reviewer/SDD ledger.
- No statistical calibration claim without representative labeled calibration data.
