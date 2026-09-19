# PR-16 — Provider Trust Anchor and Restricted Runtime Profile

Date: 2026-09-19

## Problem

PR-15 hardened the provider data protocol. The executable boundary still had two ambient-state risks:

1. the trusted registry could be filesystem-mutable by another POSIX principal;
2. a digest-pinned provider still inherited user HOME/temp/PATH state.

That ambient state can expose credentials, configuration, helper binaries, and mutable user files to a provider even when its executable identity is pinned.

## Research / guidance basis

### Python subprocess environment semantics

https://docs.python.org/3/library/subprocess.html

Python documents that when `env` is supplied to `Popen`, it replaces the inherited environment. This gives the control plane a deterministic place to enforce least-privilege process state.

### Python tempfile

https://docs.python.org/3/library/tempfile.html

`TemporaryDirectory` securely creates an ephemeral directory and removes it after use. Explicit `dir`/runtime paths avoid relying on ambient TMPDIR/TEMP/TMP selection.

### Python stat

https://docs.python.org/3/library/stat.html

POSIX mode bits expose group/other write permissions and support fail-closed validation of trust-anchor files where the platform provides those semantics.

### OWASP AI Agent Security

https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

OWASP recommends least privilege, explicit tool authorization, sandboxing/isolation, protecting credentials, and restricting the runtime environment available to coding agents and tools.

### OWASP Secure Coding with AI

https://cheatsheetseries.owasp.org/cheatsheets/Secure_Coding_with_AI_Cheat_Sheet.html

Relevant guidance includes sandboxed/restricted runtimes, blocked credential-store access, egress/permission controls, ephemeral credentials, and avoiding execution with the developer's full ambient privileges.

### NIST agent identity and authorization concept paper

https://csrc.nist.gov/pubs/other/2026/02/05/accelerating-the-adoption-of-software-and-ai-agent/ipd

NIST identifies explicit authorization controls as necessary when software/AI agents gain access to tools, applications, and sensitive data.

## Trust-anchor rules

For registry-backed trusted providers:

- registry path may not be a symlink;
- registry must be a regular file;
- POSIX registry mode may not be group/world writable;
- POSIX registry owner must be the current user or root;
- trusted executable may not be group/world writable;
- executable permissions are rechecked at launch in addition to digest/path verification.

The POSIX-specific ownership/mode checks are intentionally conditional on platform support.

## Restricted runtime profile

Registry-backed providers default to `runtime_profile = "restricted"`.

Each invocation gets:

- ephemeral HOME / USERPROFILE;
- ephemeral TMPDIR / TEMP / TMP;
- minimal PATH = trusted executable directory;
- deterministic locale and Python UTF-8 settings;
- required Windows bootstrap variables only when present;
- explicitly trusted `env_allowlist` variables.

Reserved runtime identity keys cannot be overridden through the restricted profile allowlist.

## Compatibility profile

Some existing providers may intentionally require host HOME/PATH behavior. The trusted registry can opt those providers into:

```json
"runtime_profile": "compatibility"
```

Repository configuration cannot set this field, so a checked-in repository cannot weaken the runtime boundary.

## Compatibility

- legacy direct `CommandProviderSpec` construction keeps the historical compatibility profile by default;
- registry-backed providers default to restricted mode;
- the new dataclass field is appended, preserving older positional constructor semantics;
- no runtime dependency is added;
- sync and async providers use the same runtime-profile contract.
