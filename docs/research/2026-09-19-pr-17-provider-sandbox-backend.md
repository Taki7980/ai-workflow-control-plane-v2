# PR-17 — Optional Sandboxed Provider Backend

Date: 2026-09-19

## Problem

PR-16 isolated provider environment state, but it intentionally did not claim OS-level confinement. A compromised or malicious trusted provider executable could still use the host process' operating-system authority.

PR-17 adds an optional OS-enforced provider sandbox boundary with explicit network policy, per-process resource limits, fail-closed semantics, and typed audit state.

## Research / standards basis

### Sandlock — Confining AI Agent Code with Unprivileged Linux Primitives

https://arxiv.org/abs/2605.26298

Sandlock argues that meaningful agent-code confinement requires kernel-enforced filesystem, network, IPC and syscall controls rather than ad-hoc shell wrappers or environment filtering. It also emphasizes TOCTOU-safe policy enforcement and low-overhead unprivileged isolation.

PR-17 implements the subset available without adding a new runtime dependency: namespace-based filesystem/network/process isolation through Bubblewrap plus explicit per-process resource limits.

### Bubblewrap

https://github.com/containers/bubblewrap

https://manpages.debian.org/testing/bubblewrap/bwrap.1.en.html

Bubblewrap creates an isolated mount namespace and supports PID, IPC, UTS and network namespaces, read-only and writable bind mounts, capability dropping, a detached terminal session, and die-with-parent semantics.

PR-17 uses:
- read-only host root;
- explicit writable ephemeral runtime paths only;
- PID / IPC / UTS isolation;
- capability drop;
- new session;
- die-with-parent;
- optional network namespace removal.

### OWASP AI Agent Security

https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

OWASP recommends least privilege, explicit tool authorization, sandboxing arbitrary code execution, bounded recursion/resource use, and adversarial testing after material provider/tool changes.

### OWASP Secure Coding with AI

https://cheatsheetseries.owasp.org/cheatsheets/Secure_Coding_with_AI_Cheat_Sheet.html

OWASP explicitly recommends sandboxed agent runtimes, blocking unnecessary credential/config access, network egress controls, and CPU/memory/disk/process limits.

### OWASP Secure AI Model Ops

https://cheatsheetseries.owasp.org/cheatsheets/Secure_AI_Model_Ops_Cheat_Sheet.html

Relevant guidance includes per-workload CPU, memory, disk, process and network limits, restricted egress, isolated workers, and avoiding unnecessary host mounts.

### Python subprocess

https://docs.python.org/3/library/subprocess.html

Python warns that `preexec_fn` is unsafe in threaded applications because the child can deadlock before exec. PR-17 therefore does not implement limits with `preexec_fn`.

### POSIX resource limits

PR-17 applies CPU, address-space, file-size and open-file limits through a separate Python exec wrapper that invokes `setrlimit` and then replaces itself with the trusted provider executable.

This avoids running arbitrary Python callbacks in the fork-before-exec window.

## Policy model

Trusted provider registry:

```json
{
  "sandbox": {
    "mode": "required",
    "backend": "auto",
    "network": "deny",
    "limits": {
      "cpu_seconds": 10,
      "memory_mb": 512,
      "file_size_mb": 64,
      "open_files": 128
    }
  }
}
```

Repository configuration cannot modify this field.

### Modes

`off`
- no sandbox;
- current PR-16 runtime profile behavior remains.

`preferred`
- use an OS sandbox when available;
- fallback is allowed only when the policy contains no hard network/resource requirement;
- fallback is explicit in typed result metadata.

`required`
- fail closed before the provider command executes when no enforcing backend is available.

## Hard-control invariant

The following are treated as must-enforce even under `preferred`:

- `network = "deny"`;
- any configured resource limit.

If a backend cannot enforce them, provider execution returns `sandbox_unavailable` and no provider process is launched.

## Linux Bubblewrap backend

The initial backend is intentionally Linux-only.

Command construction includes:

```text
--ro-bind / /
--unshare-pid
--unshare-ipc
--unshare-uts
--proc /proc
--dev /dev
--cap-drop ALL
--new-session
--die-with-parent
[--unshare-net when network=deny]
```

Only runtime-owned ephemeral directories are rebound writable.

This gives strong write isolation and optional network isolation while retaining read access to host paths needed by dynamically linked provider installations. It is not claimed to provide the same boundary as a microVM, seccomp/Landlock policy, or dedicated container image.

## Resource limits

Supported limits:

- CPU seconds;
- virtual address-space MiB;
- file size MiB;
- open file descriptors.

The wrapper:

```text
control plane
  -> bubblewrap
    -> ai_workflow.provider_sandbox_exec
      -> setrlimit(...)
      -> subprocess.run(provider argv, shell=False)
```

No shell and no `preexec_fn` are used.

## Backend availability

Bubblewrap availability is actively probed with the exact namespace capabilities PR-17 depends on.

A present-but-unusable binary is treated as unavailable rather than being assumed to provide a security boundary.

## Typed auditability

`ProviderResult` records:

- whether sandboxing actually happened;
- effective backend;
- requested mode;
- effective network policy;
- whether resource limits were enforced;
- fallback reason, when applicable.

This prevents a soft fallback from being indistinguishable from a required sandboxed run.

## Cross-platform compatibility

No runtime dependency is added.

- Linux: Bubblewrap is used when configured and usable.
- macOS / Windows: existing provider execution remains compatible when sandbox is off.
- soft preferred mode may fall back when there are no hard controls.
- required mode / network deny / configured limits fail closed when no enforcing backend exists.

This avoids pretending that Windows/macOS received controls that PR-17 does not implement.

## Tests

Regression tests cover:

1. policy schema validation;
2. required-mode fail closed;
3. preferred soft fallback;
4. network-deny fail closed;
5. resource-limit fail closed;
6. Bubblewrap command includes read-only root and namespace controls;
7. resource limits are routed through the exec wrapper;
8. repository cannot weaken registry sandbox policy;
9. typed fallback audit state;
10. sync/async sandbox-unavailable parity;
11. provider command does not execute when a hard sandbox policy cannot be enforced;
12. real Bubblewrap write-isolation integration when the CI host exposes a usable backend.

## Scope boundary

PR-17 does not add:
- seccomp filters;
- Landlock path allowlists;
- cgroup v2 aggregate limits;
- microVM isolation;
- host-read allowlist virtualization;
- HTTP-level egress allowlisting.

Those would require additional backend/platform work and should not be implied by the current Bubblewrap profile.
