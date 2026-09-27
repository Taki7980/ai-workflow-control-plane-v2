# PR-32 — Concurrency and crash consistency

Date: 2026-09-28

## Problem

AI Workflow already uses SQLite WAL for the optional production evidence mirror,
atomic JSON replacement for mutable deployment state, generation checks for
deployment transitions, and directory locks for deployment mutation.

The remaining reliability gaps were at crash boundaries rather than normal
control flow:

1. mutable atomic replacement fsynced the file but not the containing directory;
2. immutable learning/audit records were written directly to their final
   filename, so a process kill mid-write could leave a partial file permanently
   occupying an immutable name;
3. stale deployment locks were recovered solely by age and could steal a live
   POSIX owner's lock after the fixed lease;
4. JSON/SQLite reconciliation did not mark extra mirror rows or invalid
   canonical JSON as inconsistent;
5. concurrent WAL writers lacked an explicit multi-process regression test.

## Research basis refreshed 2026-09-28

### SQLite WAL and crash behavior

SQLite documents that WAL commits are appended atomically and supports concurrent
readers with a single writer. With `synchronous=FULL`, the WAL is synced after
each transaction commit for durability across power loss.

https://www.sqlite.org/wal.html
https://www.sqlite.org/pragma.html

SQLite also documents the 2026 WAL-reset corruption bug affecting concurrent
writer/checkpoint timing through 3.51.2, fixed in 3.51.3 and later (plus selected
backports). AI Workflow already fails closed on affected runtimes; PR-32 adds
concurrency regression coverage around that policy.

https://www.sqlite.org/wal.html#walreset

SQLite warns that correct locking depends on the filesystem/VFS and calls out
network filesystems as a corruption risk when their locking semantics are broken.

https://www.sqlite.org/howtocorrupt.html

### Atomic file publication

Python documents `os.replace()` as atomic when source and destination are on the
same filesystem. Atomic replacement alone does not persist the parent directory
entry across every crash model, so PR-32 fsyncs the containing directory on
platforms where Python exposes a portable directory file descriptor.

https://docs.python.org/3/library/os.html#os.replace

## Design

### Mutable state

`atomic_write_text/json/jsonl` keeps the existing same-directory temp-file
pattern:

```text
write temp -> flush -> fsync(temp) -> os.replace(final) -> fsync(parent)
```

Windows has no portable directory-fsync primitive through Python's `os` module;
the helper reports that limitation instead of claiming a guarantee it cannot
provide.

### Immutable records

Immutable learning and deployment-audit records now use:

```text
write sibling temp -> fsync(temp) -> hard-link temp to final name -> fsync(parent)
                                              |
                                              +-> FileExistsError if already claimed
```

The final immutable filename is never exposed until the complete file has been
written and fsynced. A failed publication leaves no partial final file.

### Deployment locks

Age remains the cross-platform stale-lock fallback. On POSIX, if an expired lock
claims the current host and its PID is still alive, AI Workflow refuses to steal
the lock. This prevents a long-running live transition from being recovered
solely because its lease age exceeded the threshold.

### WAL mirror

The production store already requires:

- patched SQLite WAL runtime;
- WAL journal mode;
- `synchronous=FULL`;
- bounded busy timeout;
- `BEGIN IMMEDIATE` write transactions.

PR-32 now verifies the synchronous mode at runtime and stress-tests concurrent
writers using separate spawned processes.

Reconciliation now fails closed when any of the following are present:

- canonical JSON missing from SQLite;
- canonical/SQLite digest mismatch;
- extra SQLite rows without canonical JSON;
- unreadable or malformed canonical JSON.

The canonical JSON evidence remains authoritative; SQLite remains a same-host
query mirror.

## Fault-injection coverage

Tests simulate:

- disk-full/error before atomic replacement;
- failure while publishing an immutable record;
- duplicate immutable filename claims;
- expired lock with a live local POSIX PID;
- expired lock with a dead owner;
- fresh lock recovery refusal;
- six concurrent process writers to one WAL database;
- invalid canonical JSON;
- extra SQLite-only events;
- corrupt SQLite database bytes.

## Important limitations

- Directory fsync has no portable stdlib implementation on Windows; Windows
  relies on the operating system semantics of the completed file/replace call.
- The deployment directory lock is intended for same-host/local-filesystem use,
  not distributed consensus or unreliable network filesystems.
- Hard-link publication requires a filesystem supporting hard links; failure is
  surfaced rather than silently falling back to unsafe direct-final writes.
- These tests model application/process/I/O failures. They do not emulate every
  storage-controller, kernel, or hardware power-loss behavior.
- SQLite integrity still depends on correct OS/filesystem locking and sync
  semantics.

## Acceptance criteria

- no partial immutable final record is observable before publication;
- mutable replacement preserves the previous file if publication fails;
- parent directory sync is attempted after publication where supported;
- live local POSIX lock owners are not stolen by lease age alone;
- concurrent WAL writers commit without corruption;
- WAL store enforces FULL synchronous mode;
- invalid, missing, mismatched, or extra mirror evidence fails reconciliation;
- corrupt SQLite fails closed;
- full cross-platform CI/security/benchmark matrix passes before merge readiness.
