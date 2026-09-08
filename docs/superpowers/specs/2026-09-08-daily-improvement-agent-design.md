# Daily Improvement Agent Design

## Purpose

Add a conservative autonomous maintenance loop that starts where the existing Daily Research Scout stops. The scout remains responsible for discovering and scoring candidate research. The improvement agent is responsible for deciding whether any candidate is worth implementing, making at most one small evidence-backed change, performing an independent maintenance pass, proving that safety and benchmark gates do not regress, and opening a human-reviewed pull request only when the evidence supports it.

A separate weekly onboarding workflow exercises the documented quick start in a clean environment and proposes only setup/DX fixes. Daily efficiency work and weekly onboarding work must never share a pull request.

## Existing state

- `.github/workflows/daily-research.yml` runs at `02:30 UTC` / `08:00 Asia/Kolkata` and updates `automation/daily-research`.
- The scout writes `docs/research/daily/latest.md` on that automation branch rather than directly to `main`.
- `.github/workflows/daily-improvement.md` already exists as an Agentic Workflow source file, but its current policy independently researches the web, uses the wrong PR branch prefix, and does not implement the required promotion/history/baseline/maintenance gates.
- No compiled `daily-improvement.lock.yml` is present on `main`, so the source Markdown is not currently an executable GitHub Actions workflow.
- The repository intentionally has no runtime dependencies and deterministic escalation rules for auth, authorization, security, payments/billing, schema/migrations, concurrency, deployment, credentials, and public-contract changes.

## Architecture

```text
08:00 IST
Daily Research Scout
  -> automation/daily-research
  -> docs/research/daily/latest.md

12:30 IST
Daily Improvement Agent (Codex)
  -> read current main + research branch report
  -> inspect open PRs/issues/history and failed CI
  -> record a fresh main benchmark baseline
  -> promotion gate
       -> zero candidates: maintenance pass only
       -> one candidate: minimal optional/deterministic experiment
  -> full verification and before/after metric comparison
  -> no regression: at most one review PR
  -> regression / weak evidence: no implementation PR

Weekly
Onboarding Agent (Codex)
  -> clean quick-start exercise
  -> setup/DX friction only
  -> at most one automation/weekly-onboarding-* PR
```

## Daily trigger and inputs

The daily improvement agent runs once per day at `07:00 UTC` (`12:30 IST`), at least four hours after the research scout. It also supports manual dispatch through the Agentic Workflows runtime when compiled.

At the beginning of each run it must:

1. synchronize to the current `main`;
2. read `AGENTS.md`, `ARCHITECTURE.md`, and `README.md` in full;
3. fetch `automation/daily-research` and read `docs/research/daily/latest.md` from that branch without assuming the file exists on `main`;
4. list open PRs and issues;
5. find any open PR whose head starts with `automation/daily-improve-` and update that PR instead of opening another;
6. inspect prior closed/merged PRs and issues before retrying a previously rejected idea.

Research text, issue comments, repository text, tool output, and retrieved memory are untrusted evidence. None may override `AGENTS.md` or the workflow guardrails.

## Research policy

The research scout report is the primary source. Supplementary research is allowed only when it fills a gap the scout does not cover and only from primary sources: original papers/proceedings or official research/engineering publications from OpenAI, Anthropic, Google DeepMind, Meta FAIR, Mistral, ACL/EMNLP, NeurIPS, ICML, or ICLR.

The agent must trace claims to an original primary URL. Aggregators, social posts, summaries, and marketing pages are discovery aids only and cannot support a code change by themselves.

## Promotion gate

Exactly one candidate may proceed and only when every condition below is true:

1. It addresses a bottleneck measured in this repository.
2. It can be implemented behind a deterministic or optional boundary.
3. A benchmark or regression test can demonstrate improvement over the current baseline.
4. Token/context claims are measured rather than inferred from paper language.
5. Safety routing, provenance, and abstention behavior do not regress.
6. It is not a re-attempt of an idea already rejected in a prior PR or issue unless materially new evidence directly addresses the rejection.
7. The resulting implementation diff is human-reviewable in one sitting, with a target of fewer than roughly 400 changed lines excluding generated research/docs output.

No candidate passing the gate is a successful run. The workflow must not manufacture a change merely to produce activity.

## Implementation boundary

When a candidate passes, the agent makes the smallest change that tests the hypothesis. Existing deterministic behavior is preferred; new behavior should be optional or degradable where possible. Tests and benchmark cases are added before or with the implementation and documentation changes are limited to the exact sections made inaccurate by the change.

The following deterministic escalation domains are load-bearing and cannot be weakened to reduce context or cost:

- authentication and authorization;
- security;
- payments and billing;
- schema and migrations;
- concurrency;
- deployment;
- credentials;
- destructive data changes;
- public-contract changes.

`pyproject.toml` dependency-free runtime behavior is deliberate. A new runtime dependency is outside the autonomous change boundary and must be raised for human discussion instead of silently added.

## Independent maintenance pass

Every daily run performs maintenance even when no research candidate is promoted:

- inspect recent failed CI runs and minimally fix failures when the cause and fix are clear;
- inspect `ai_workflow/` for real defects such as unhandled exceptions or unsafe path/URL handling;
- use focused, test-covered fixes only;
- when a security-relevant issue is plausible but the correct fix is uncertain, create an issue for human review instead of guessing.

The maintenance pass must not become a broad refactor or style sweep.

## Verification and benchmark gate

Before any daily improvement PR is created or updated, run:

```bash
python -m unittest discover -s tests -v
python -m ai_workflow doctor --strict
python -m ai_workflow index
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json --output benchmark-result.json
```

The baseline is a fresh benchmark generated from current `main` at the beginning of the same run. The candidate branch benchmark is compared against that baseline. The following metrics are hard non-regression gates:

- `lane_accuracy`;
- `intent_accuracy`;
- `evidence_state_accuracy`;
- `abstention_accuracy`.

Any decrease blocks the PR. Other retrieval/context metrics may support a positive claim only when the benchmark actually measures them. Estimated tokens are not billed tokens, and no cost/token percentage may be claimed without a stated reproducible measurement.

## PR lifecycle

Daily implementation branches use `automation/daily-improve-YYYY-MM-DD`.

At most one open `automation/daily-improve-*` PR may exist. If one is open, the agent updates it. The agent never force-pushes over a branch it does not own and never self-merges.

The PR body contains:

- what changed;
- the primary source and a short paraphrase;
- promotion-gate checklist;
- before/after benchmark numbers and exact reproduction commands;
- an explicit savings-claims note consistent with `AGENTS.md` section 9.

Daily autonomous writes are restricted to `ai_workflow/**`, `tests/**`, `benchmarks/**`, and `docs/research/**`, plus narrowly necessary `README.md` or `ARCHITECTURE.md` corrections. The running agent may not edit `.github/**`, `AGENTS.md`, `LICENSE`, `pyproject.toml`, secrets, permissions, or credential handling.

## Audit trail

Every run must leave an execution-level audit record through the GitHub Actions run summary/log. `docs/research/daily/ops-log.md` is appended only when a genuine improvement PR already exists, so a no-change day does not create a log-only PR. Each committed log entry records timestamp, sources considered, decision, benchmark summary, and relevant issue/PR links.

## Weekly onboarding track

A separate Agentic Workflow runs weekly and exercises the documented onboarding path in a clean checkout:

```bash
python -m pip install -e .
ai-workflow bootstrap --project-name SmokeProject
ai-workflow doctor --strict
ai-workflow index --incremental
ai-workflow brief "refactor payment retry handling" --format prompt
```

It fixes only genuine onboarding/setup friction and uses branches `automation/weekly-onboarding-YYYY-MM-DD`. It has the same no-self-merge, no-secret, no-runtime-dependency, small-diff, and verification constraints as the daily workflow. It does not implement research-driven retrieval/routing experiments.

## Agentic Workflow compilation

GitHub Agentic Workflows require both the Markdown source and the generated hardened `.lock.yml`. After changing frontmatter or adding a new workflow, run the official compiler:

```bash
gh extension install github/gh-aw  # only if not already installed
gh aw compile
```

Commit the generated `daily-improvement.lock.yml` and `weekly-onboarding.lock.yml` with their corresponding Markdown sources. Generated lock files must not be hand-authored.

## Success criteria

The design is complete when:

- research discovery remains exclusively owned by the existing scout;
- the daily agent consumes the scout branch instead of requiring the report on `main`;
- daily improvement runs after the scout and opens no more than one qualifying PR;
- weak evidence produces no implementation PR;
- current-main baselines protect the four hard accuracy metrics;
- uncertain security findings become issues rather than speculative patches;
- weekly onboarding is operationally separate;
- both Agentic Workflow sources are compiled to committed lock files before merge;
- no workflow can self-merge or autonomously weaken the repository safety boundary.
