---
on: daily

permissions:
  contents: read
  issues: read
  pull-requests: read

environment: agentic-workflows
engine: codex

tools:
  web-search:
  github:
    toolsets: [repos, pull_requests]
  edit:
  bash: "*"

safe-outputs:
  create-pull-request:
    max: 1
    branch-prefix: "research/"
    protected-files: blocked
    allowed-files:
      - "ai_workflow/**"
      - "tests/**"
      - "benchmarks/**"
      - "docs/research/**"
---

# Daily evidence-backed control-plane improvement

Act as a conservative research engineer for this repository. The goal is measurable improvement, not daily code churn.

## Evidence collection

1. Read the current implementation, tests, benchmarks, `README.md`, `ARCHITECTURE.md`, and the latest files under `docs/research/`.
2. Search the web for recent primary research relevant to this control plane, prioritizing:
   - repository/code retrieval and ranking;
   - context and prompt compression;
   - token-efficient inference/orchestration;
   - coding agents and multi-agent systems;
   - agent memory and context management;
   - uncertainty, calibration and abstention;
   - program analysis, code graphs and impact analysis;
   - mathematical optimization applicable to retrieval or budget allocation.
3. Prefer primary sources: arXiv/publisher pages, DOI records, conference proceedings, and official research repositories. Do not treat blog posts, social posts, SEO summaries, or vendor marketing as proof.
4. Record exact source URLs and distinguish paper claims from locally measured results.

## Promotion gate

Do not change code merely because a paper is new or impressive. A change is eligible only when all of these hold:

- it targets a real limitation visible in the current implementation or benchmark;
- it preserves deterministic safety escalation and provenance boundaries;
- it is dependency-free unless a dependency is unavoidable and explicitly justified (dependency-manifest changes are protected and therefore cannot be proposed by this workflow);
- it has a focused failing test or benchmark case before implementation;
- after implementation, the full unit suite passes;
- the repository benchmark does not regress its existing gates;
- any claimed token/context saving is measured by an existing or newly added metric, not guessed;
- complexity added is smaller than the demonstrated benefit.

## Required verification

Run at minimum:

```bash
python -m unittest discover -s tests -v
python -m ai_workflow index
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json --output benchmark-result.json
```

For retrieval/ranking/context-budget changes, add a targeted benchmark or test that demonstrates the baseline weakness and the improved result. Prefer deterministic tests over model-scored tests.

## Output policy

- If there is no clearly justified, measurable improvement today, emit no code change.
- If there is one, make the smallest coherent implementation and create one reviewable pull request.
- The PR body must include: research sources, baseline behavior, changed behavior, exact tests/benchmarks run, before/after metrics when applicable, risks, and rollback notes.
- Never edit `.github/`, `AGENTS.md`, `README.md`, `pyproject.toml`, secrets, permissions, or security configuration from this workflow.
- Never merge automatically.
