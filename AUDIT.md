# Project audit â€” 2026-09-05

## What runs

This is a Python 3.10+ CLI, not a frontend application. `ai_workflow/cli.py`
connects task classification, provider detection, budget allocation, context
retrieval, indexes, memory, handoff validation, and explicit verification.
Execution itself belongs to the calling agent/harness. Superpowers, Code Review
Graph, and RTK are optional integrations; PowerShell scripts are supported CLI
entry points. The package declares no runtime dependencies.

## Cleanup

Removed 11 tracked files containing obsolete scaffolding:

- `ai-workspace/agents/brain/`: two deprecated Markdown markers, no knowledge entries.
- `ai-workspace/agents/references/`: two legacy pointers to generated JSONL indexes.
- `ai-workspace/agents/skills.index.yaml`: empty `skills: []`, no runtime reader.
- `ai-workspace/Obsidian/`: five editor settings files and one unused incident template; no project notes.

Reference searches found no runtime or test consumers of these files. Updated
the workspace, migration, and domain documentation to match. Retained wrappers
because their command names are explicitly supported, and retained runtime
configuration, domain/research inputs, durable memory, tests, and benchmarks.
No runtime behavior was changed in this cleanup.

## Confirmed gaps ? resolved

| Gap | Resolution |
| --- | --- |
| Blank verification commands could pass without execution. | Blank commands fail explicitly; success requires actual results. Regression covers empty and mixed command lists. |
| Unbounded short mutations selected Small. | Small mutations require one or two explicit file hints; unscoped cleanup defaults Full. Existing risk escalation remains first. |
| Answer briefs wrote snapshots and memory state. | Answer writes neither snapshot nor handoff; shared memory read paths no longer create directories or files. Whole-tree snapshots verify no changes. |
| Fresh-directory initialization reported success with missing configuration. | Init validates existing configuration and reads AGENTS.md before writing. Missing templates fail with setup guidance; invalid config leaves no state. |
| CI targeted unsupported Python versions and omitted tests. | CI runs unittest on Python 3.10 through 3.14 on Linux, plus Python 3.14 on Windows. Replaced standalone Pylint workflow; no new dependency. |
| PowerShell ignored -Incremental. | Wrapper forwards --incremental; executable PowerShell regression checks both modes. |

Initialization intentionally requires an existing template; it does not create a
second set of embedded templates. Routing remains a keyword/file-hint heuristic,
so callers must escalate ambiguous scope rather than treating it as a safety proof.

## Validation scope

Baseline: all 51 unit tests passed on Python 3.14.7; `doctor --strict` passed.
Code Review Graph is installed locally but has no ready graph; this optional
integration falls back to source search. This audit did not install or configure providers.
After fixes, all 60 tests and `doctor --strict` passed locally on Python 3.14.7. `git diff --check`
passed, and reference searches found no remaining consumers of removed paths
outside the cleanup inventory and handoff.

The audit traced the CLI, routing, retrieval inputs, initialization, verification,
compatibility scripts, and CI. It is not an exhaustive security or performance audit.
