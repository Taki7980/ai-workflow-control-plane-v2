# External Provider Launch Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the remaining trusted external-provider launch boundary without rebuilding controls already present on main.

**Architecture:** Keep the existing trusted user/admin registry, repository-command fail-closed policy, restricted environment, timeout/output caps, process-tree termination, and path confinement. Extend the immutable provider spec with launch-time executable identity, neutral-CWD, and stderr policy; enforce the same trust checks in sync and async runners; and surface only bounded/redacted diagnostics.

**Tech Stack:** Python 3.11+, hashlib/hmac, pathlib, tempfile, subprocess/asyncio, threading, unittest.

**Spec:** PR-07 / I-025–I-028 from the hardening tracker, grounded in `AI Workflow v2 Repository Deep Research and Engineering Assessment` (2026-09-15) and current 2026 OWASP/Microsoft agent-tool security guidance.

## Global Constraints

- Preserve repository-defined provider commands as disabled by default.
- Preserve the user/admin-owned trusted provider registry outside the repository.
- Preserve shell-free argv execution.
- Preserve restricted environment inheritance and explicit trusted-registry env allowlists.
- Preserve stdout byte caps, timeouts, and process-tree termination.
- Preserve provider-returned workspace path confinement.
- Do not add a mandatory Docker/microVM/OS sandbox in PR-07.
- Do not add network egress policy in PR-07; it requires a portable execution-platform design and belongs in a later security stage.
- Trusted provider launch failures must fail closed.
- Sync and async command runners must enforce the same trust policy.
- TDD: production behavior is added only after a regression test fails for the intended reason.
- Do not merge PR-07 automatically.

---

### Task 1: Carry trusted executable identity into launch — I-025

**Files:**
- Modify: `ai_workflow/provider_runner.py`
- Modify: `ai_workflow/provider_registry.py`
- Test: `tests/test_provider_security.py`

**Interfaces:**
- `CommandProviderSpec.executable_sha256: str | None`
- Trusted registry resolution copies its already-validated SHA-256 into the immutable spec.
- `verify_provider_executable(spec, root) -> Path` revalidates immediately before process creation.
- Trust failure maps to `ProviderResult.error_kind == "provider_trust"`.

- [ ] Write a failing registry test proving trusted specs retain the executable SHA-256.
- [ ] Write a failing run test: resolve a copied executable, mutate it after registry resolution, then assert launch is refused with `provider_trust`.
- [ ] Add normalized SHA-256 validation to `CommandProviderSpec`.
- [ ] Propagate registry SHA-256 into the trusted spec.
- [ ] Implement launch-time regular-file/outside-workspace/digest verification.
- [ ] Call the verifier immediately before both sync `Popen` and async `create_subprocess_exec`.
- [ ] Keep unsafe legacy providers without an expected digest explicitly marked as untrusted compatibility execution.

### Task 2: Ephemeral neutral CWD for trusted providers — I-026

**Files:**
- Modify: `ai_workflow/provider_runner.py`
- Modify: `ai_workflow/provider_registry.py`
- Test: `tests/test_provider_security.py`
- Update: `docs/provider-protocol.md`

**Interfaces:**
- `CommandProviderSpec.neutral_cwd: bool`
- Trusted registry defaults `neutral_cwd=true`.
- Trusted registry may explicitly set it false only in the user/admin-owned registry for compatibility.
- Repository project configuration cannot change it.
- Neutral execution uses a unique temporary directory for the provider lifetime and removes it after the process exits.

- [ ] Write a failing test that a trusted provider reports a CWD different from both repository and executable directory.
- [ ] Assert the reported temporary CWD no longer exists after the result returns.
- [ ] Write a failing test that repository provider configuration cannot set `neutral_cwd`.
- [ ] Add the spec field and trusted-registry default.
- [ ] Introduce a launch-context helper that yields the selected CWD and owns temporary-directory cleanup.
- [ ] Reuse the same launch-context behavior in sync and async runners.
- [ ] Preserve legacy unsafe-command repository CWD behavior behind the existing explicit unsafe flag.

### Task 3: Reject symlinked trusted executable authority — I-027

**Files:**
- Modify: `ai_workflow/provider_registry.py`
- Modify: `ai_workflow/provider_runner.py`
- Test: `tests/test_provider_security.py`

**Interfaces:**
- A trusted registry executable path must itself be a non-symlink absolute regular file.
- Launch-time verification repeats non-symlink + regular-file + workspace-separation checks.
- Existing argument resolution continues to reject repository-owned scripts/helpers.

- [ ] Write a failing test using a symlink to a valid executable in the trusted registry.
- [ ] Reject `Path.is_symlink()` before `resolve(strict=True)`.
- [ ] Repeat the same check at launch so replacing the configured executable path with a symlink after registry resolution fails closed.
- [ ] Keep existing repository-owned argument rejection tests green.

### Task 4: Bounded and redacted stderr diagnostics — I-028

**Files:**
- Modify: `ai_workflow/provider_runner.py`
- Modify: `ai_workflow/retrieval_contracts.py`
- Modify: `ai_workflow/provider_registry.py`
- Test: `tests/test_provider_security.py`
- Update: `docs/provider-protocol.md`

**Interfaces:**
- `CommandProviderSpec.max_stderr_bytes: int = 64 * 1024`
- `ProviderResult.stderr_tail: str | None`
- `ProviderResult.stderr_truncated: bool`
- stderr is fully drained to prevent child blocking while only the last configured bytes are retained.
- Redaction removes literal values from trusted `env_allowlist` variables plus common bearer/API-key/token/password/secret assignments.
- stderr never becomes a `ContextItem`.

- [ ] Write a failing sync test: provider writes > limit to stderr, includes an allowlisted secret at the tail, exits nonzero; assert bounded, truncated, redacted diagnostics.
- [ ] Write the equivalent failing async test.
- [ ] Add typed stderr fields to `ProviderResult` and `error_dict()`.
- [ ] Implement a draining bounded-tail reader for sync and async stderr.
- [ ] Implement deterministic redaction after decoding.
- [ ] Attach diagnostics to timeout/output-limit/exit/empty/invalid-payload results without changing retrieved evidence.
- [ ] Make repository configuration unable to expand `max_stderr_bytes`; trusted registry owns the cap.

### Final verification

- [ ] Run focused provider-security tests.
- [ ] Run all unit tests on Linux Python 3.11–3.14, Windows 3.14, and macOS 3.14.
- [ ] Run quality, package/install smoke, benchmark regression, and real CRG contract.
- [ ] Run Python security, full-history secret scan, and container scan.
- [ ] Review changed files for PR-08+ scope creep.
- [ ] Update provider protocol docs with exact trust/CWD/stderr semantics.
- [ ] Open/mark PR-07 ready only when the exact head is fully green.
- [ ] Leave PR unmerged for explicit human approval.
