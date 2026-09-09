# Incremental indexing

`ai-workflow index --incremental` now uses file metadata to avoid hashing source files that are unchanged since the previous successful index.

Each version-2 index-state entry records:

- `sha256` — content identity used by freshness checks;
- `size` — file size in bytes;
- `mtime_ns` — nanosecond modification time.

## Fast mode

```bash
ai-workflow index --incremental
```

If both `size` and `mtime_ns` match the previous state, the stored SHA-256 digest is reused and the file is not re-read or reparsed. Files whose metadata changed are hashed; only files whose digest changed are reparsed.

Older version-2 states that contain only `sha256` remain readable. The first incremental run hashes those files once and upgrades the state with `size` and `mtime_ns`.

Deleted files are removed from the generated indexes and state.

## Strict verification

```bash
ai-workflow index --incremental --strict-hash
```

Strict mode hashes every current source file regardless of metadata. Use it when validating an index after unusual filesystem operations, timestamp restoration, copied worktrees, or whenever content identity matters more than fast-path performance.

Strict mode is intentionally opt-in because its I/O cost is similar to the old incremental behavior.

## Correctness model

Normal mode treats matching `(size, mtime_ns)` as a candidate-reuse signal, not as a replacement for content identity. The stored SHA-256 remains the canonical digest in index records and freshness checks. Strict mode is available to verify that the metadata fast path has not hidden a content change.