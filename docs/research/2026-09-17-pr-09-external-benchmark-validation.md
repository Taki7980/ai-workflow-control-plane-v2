# PR-09 — External Benchmark Validation

Checked: 2026-09-17

## Goal

PR-09 adds a reproducible boundary for evaluating AI Workflow against external repository-retrieval datasets without copying those datasets into this repository and without inventing labels they do not provide.

The existing corpus-v2 and benchmark protocols remain authoritative. This PR only adds adapters and cross-corpus readiness reporting.

## Supported external adapters

### Agent Retrieval Bench

Source:
- paper: arXiv:2607.24882
- repository: https://github.com/eyuansu62/agent-retrieval-bench

The current upstream benchmark exposes file-level cases with fields including repository identity, frozen `base_commit`, task type, query payload, and task-specific gold files.

AI Workflow imports those records as **schema-v1 benchmark cases inside a schema-v2 corpus document**. This is intentional: file-level ARB records do not automatically become span-labelled cases, so the adapter does not fabricate `gold_spans` or `content_manifest_sha256`.

Example:

```bash
ai-workflow benchmark-corpus import-arb \
  --input /local/path/code2test.jsonl \
  --output /local/path/arb-corpus.json \
  --corpus-id arb-v0.1-code2test \
  --source-url https://github.com/eyuansu62/agent-retrieval-bench \
  --license-statement "Use under upstream benchmark and referenced repository terms" \
  --split test
```

### CORE-Bench retrieval evaluation

Source:
- paper: arXiv:2606.11864
- evaluation repository: https://github.com/zhangfw123/CORE-Bench-Eval

The retrieval evaluation uses repository-scoped `queries.jsonl`, `qrels.jsonl`, and `corpus.jsonl` files. Positive qrels are joined to corpus entries and normalized to file-level gold paths.

Example:

```bash
ai-workflow benchmark-corpus import-core \
  --queries /local/path/queries.jsonl \
  --qrels /local/path/qrels.jsonl \
  --corpus /local/path/corpus.jsonl \
  --output /local/path/core-corpus.json \
  --repository-id owner/repository \
  --base-commit 0123456789abcdef0123456789abcdef01234567 \
  --corpus-id core-level2-owner-repository \
  --source-url https://github.com/zhangfw123/CORE-Bench-Eval \
  --license-statement "Use under upstream dataset and repository terms" \
  --split test \
  --language python
```

The adapter fails closed when a positive qrel references a missing corpus entry or when a relevant corpus entry cannot be resolved to a file path.

## Cross-corpus report

Multiple normalized external corpora can be checked together:

```bash
ai-workflow benchmark-corpus external-report \
  --input arb-corpus.json \
  --input core-corpus.json \
  --minimum-languages 4 \
  --require-ready
```

The report checks:
- required external source families are represented;
- corpus IDs are unique;
- case counts;
- repository diversity;
- language diversity;
- each input still satisfies the existing corpus-v2 validation contract.

This report is a **corpus coverage/readiness report**, not a retrieval-performance claim. Retrieval quality still requires running the normalized cases through the normal benchmark commands against the corresponding frozen repository snapshots.

## ContextBench status

ContextBench (arXiv:2602.05892; https://github.com/EuniAI/ContextBench) contains broader human-annotated context evidence across many repositories and languages. PR-09 keeps it registered as a future span/trajectory source rather than marking it implemented. A later adapter should preserve its native annotation semantics rather than coercing those labels into file-only gold.

## Integrity and licensing boundaries

- AI Workflow does not download external benchmark data automatically.
- No external benchmark rows are vendored into this repository.
- The user/operator supplies local dataset files and corresponding repository snapshots.
- Source URL and license statements are embedded into normalized corpus metadata.
- The adapters do not infer redistribution rights for benchmark data or referenced source repositories.
- Missing span labels, content manifests, repository commits, or file identities are not synthesized.
- External source data is treated as evaluation input, not trusted executable configuration.

## Non-claims

PR-09 does not claim:
- that merely importing ARB or CORE-Bench reproduces their published scores;
- that external datasets are publication-ready after normalization;
- that file-level labels are equivalent to line/span-level context labels;
- that four-language coverage proves multilingual retrieval quality;
- that ContextBench is implemented in this PR;
- that external benchmark licenses permit redistribution by this project.

The purpose of the adapter layer is to make independent evaluation possible while keeping provenance, frozen repository identity, and missing-label limitations explicit.
