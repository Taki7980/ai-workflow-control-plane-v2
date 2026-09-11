# Benchmark Corpus v2

This directory defines the research-data contract used by AI Workflow Stage 9.

It intentionally does **not** vendor large third-party benchmark corpora or copied
repository snapshots. External benchmark data should remain in its upstream source
unless its license explicitly permits redistribution.

## Goals

Corpus v2 adds the evidence properties missing from the legacy 32-case smoke set:

- clean frozen repository contents, not only a matching Git HEAD;
- stable repository identity;
- file-level and line/span-level gold;
- natural no-gold and wrong-repository control provenance;
- fixed token and optional line budgets;
- label source and labeler-count metadata;
- machine-readable source/licensing provenance;
- explicit publication-readiness reporting.

The legacy `benchmarks/sample-tasks.json` remains a regression smoke suite. It is not
presented as a publication-scale research corpus.

## Author a snapshot

From the workspace containing the repository:

```bash
ai-workflow benchmark-corpus snapshot --repository path/to/repo --strict
```

The output contains:

```json
{
  "status": "captured",
  "actual_head": "<git commit>",
  "worktree_clean": true,
  "content_manifest_sha256": "<sha256 of git ls-tree -r -z HEAD>",
  "repository_path": "path/to/repo"
}
```

The manifest is intentionally independent of Git's object-hash algorithm. In strict
benchmark execution, a case passes only when:

```text
HEAD == base_commit
AND worktree is clean
AND content manifest matches when declared
```

## Corpus document

A runnable corpus-v2 file is a JSON object:

```json
{
  "schema_version": 2,
  "corpus_id": "example-test-split",
  "source": {
    "name": "upstream benchmark or human-labelled corpus",
    "url": "https://example.org/source",
    "license": "verify and record the applicable license"
  },
  "split": "test",
  "cases": [
    {
      "schema_version": 2,
      "case_id": "comment2context-0001",
      "task": "Where is refresh-token rotation implemented?",
      "task_type": "comment2context",
      "control_type": "positive",
      "repository_id": "backend-repo",
      "repository_path": ".",
      "base_commit": "<40-64 hex commit id>",
      "content_manifest_sha256": "<64 hex sha256>",
      "gold_files": ["src/auth/token_service.py"],
      "gold_spans": [
        {
          "repository_id": "backend-repo",
          "path": "src/auth/token_service.py",
          "start_line": 118,
          "end_line": 171
        }
      ],
      "language": "python",
      "label_source": "human_and_verified_patch",
      "labeler_count": 2,
      "budget_tokens": 8192,
      "budget_lines": 400,
      "retrieval_k": 20
    }
  ]
}
```

Selective controls must contain no gold files/spans and must add
`control_source` explaining how the control was obtained. This is provenance,
not a claim that a query is automatically "natural".

## Validate

```bash
ai-workflow benchmark-corpus validate --input corpus.json
```

For a publication gate:

```bash
ai-workflow benchmark-corpus validate \
  --input corpus.json \
  --require-ready
```

The current readiness floor is deliberately conservative and based on reaching at
least Agent Retrieval Bench scale:

- >= 427 cases;
- >= 25 repositories;
- >= 4 languages;
- at least one natural no-gold control;
- at least one wrong-repository control;
- span-labelled cases present.

Clearing this floor does **not** prove benchmark quality. It only prevents obviously
underpowered/demo corpora from being described as research-scale evidence.

## Run

```bash
ai-workflow benchmark \
  --tasks corpus.json \
  --research-protocol \
  --require-frozen-snapshot \
  --output results.json
```

The result includes file metrics plus span/line metrics:

- span Precision@k / Recall@k / F1;
- line precision / line recall;
- first gold span rank;
- covered gold lines;
- gold-line yield per 1K estimated context tokens.

When `budget_tokens` is supplied, that case overrides the normal lane context
ceiling for the benchmark only. `budget_lines` constrains the span-scoring view
so systems can be compared at a fixed line budget.

## External sources

See `sources.json`. It is a source registry only. Adapters should preserve upstream
IDs, licenses, repository commits, and original labels. Do not synthesize missing
gold labels merely to increase corpus size.
