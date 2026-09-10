# Core contracts and safe setup

This document records the lightweight boundaries introduced by the technical audit hardening work.

## Safe setup

`ai-workflow setup` now requires the selected project root to exist. This prevents a mistyped path from silently creating a second project tree. Creating a missing root is explicit:

```bash
ai-workflow --root ./new-project setup --create
```

Setup builds a full index the first time and switches to incremental indexing when an index state already exists. Index work can be intentionally skipped with `--no-index`.

The `.ai/PROJECT` marker stores `.` instead of an absolute checkout path, so copied/moved repositories do not retain machine-specific locations.

## Content identity

`ContextItem.dedupe_key` is a BLAKE2 digest of canonical whitespace-normalized content. Source labels are observations, not content identity.

Generated setup files, handoffs, briefs, benchmark output, and index state use a shared temp-file + `os.replace` writer so a failed replacement leaves the previous valid file intact.

## Typed execution contract

`OrchestrationContract` is a `TypedDict`: runtime JSON shape stays backward-compatible while type checkers can validate the complexity vector, bounded agent slots, review/verification passes, CRG plan, and Superpowers sequence.

## Selector complexity bound

`context.selector.max_selector_candidates` defaults to 200. Candidates are deduplicated and cheaply relevance-ranked first; facility-location coverage runs only on the bounded candidate universe. Mandatory structural sources are preserved within the bound.

## Token estimates

Core token counts remain explicitly estimates. `TokenEstimator` is a protocol and the default `CharacterTokenEstimator` preserves the dependency-free four-character approximation. Provider/model integrations can inject an exact tokenizer without making it a core dependency.

## Machine diagnostics

Doctor output has `schema_version: 1`, a stable `core_ok` field, explicit `optional_capabilities`, and documented exit-code meanings. Missing optional CRG/Superpowers/ripgrep/semantic integrations are reported separately from core correctness.

## Hash verification naming

Both spellings are supported for strict incremental verification:

```bash
ai-workflow index --incremental --strict-hash
ai-workflow index --incremental --verify-hashes
```
