# PR-15 — Provider Protocol / Schema Hardening

Date: 2026-09-19

## Why this PR exists

Command providers are trusted executables but their stdout remains an untrusted
data boundary. Before PR-15, Python's permissive JSON decoder and tolerant item
coercions allowed ambiguous or non-standard numeric values to cross that
boundary.

## Research / standards basis

### RFC 8259 — JSON

https://www.rfc-editor.org/rfc/rfc8259.html

RFC 8259 explicitly states that numeric values such as `Infinity` and `NaN`
are not permitted and allows implementations to define numeric range/precision
limits.

### Python `json` documentation

https://docs.python.org/3/library/json.html

Python accepts `NaN` and infinities by default. The documented
`parse_constant` hook exists specifically so callers can reject these
non-standard constants.

Python also accepts duplicate object member names by default and keeps the last
value. PR-15 rejects duplicates at the provider boundary to avoid ambiguous
parser behavior.

### OWASP Input Validation

https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html

OWASP recommends strong type checks, minimum/maximum numeric ranges, string
length limits, allowlist validation, and rejecting unexpected/illegal content.

### OWASP REST Security

https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html

Relevant guidance includes validating type, length, range, format, message size,
and rejecting illegal content at structured API boundaries.

### Hypothesis

https://hypothesis.readthedocs.io/en/latest/

Property-based testing is used in the Security workflow to generate malformed
bytes, floating-point edge cases, and recursively structured metadata so the
parser boundary is exercised beyond hand-written examples.

## Strict response contract

PR-15 now fails the whole provider response closed when it contains:

- `NaN`, `Infinity`, `-Infinity`;
- finite JSON syntax that overflows to an infinite float;
- duplicate JSON keys;
- non-object records;
- more than 1024 records;
- excessive nesting/container/string bounds;
- non-numeric or non-finite scores;
- scores outside `0.0..1.0`;
- non-boolean `stale`;
- non-object `metadata` or `provenance`;
- invalid line/end-line types or bounds;
- invalid bounded string fields.

Missing score remains `0.0`. A malformed score no longer degrades silently to
zero.

## State contamination controls

A rejected response becomes:

```text
ProviderResult(
  items=(),
  error_kind="invalid_payload"
)
```

Therefore raw rejected payload values cannot enter the candidate ranker.

`FileRetrievalCache.put()` already rejects failed provider results and now also
refuses otherwise-typed results containing non-finite latency or item scores as
a defense-in-depth invariant.

Learning may observe that a provider failed, but rejected provider values are
never converted into selected evidence, scores, cache entries, or learned
payload-derived features.

## Fuzzing / property tests

The Security workflow now exercises:

1. arbitrary provider stdout bytes;
2. all floating-point classes including NaN/infinity;
3. recursively generated JSON metadata;
4. typed-failure invariants;
5. normalized score-domain invariants.

The fuzz/property tests require that malformed data is either accepted as
bounded valid protocol data or converted into a typed failure with zero items.

## Compatibility

- request format is unchanged;
- valid provider response envelopes remain JSON / JSONL;
- no runtime dependency added;
- Hypothesis was already pinned in the Security test environment;
- output byte/time/process boundaries are unchanged;
- repository path confinement and PR-13/PR-14 trust boundaries remain intact.
