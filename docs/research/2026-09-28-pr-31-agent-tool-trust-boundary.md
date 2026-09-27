# PR-31 — Agent and tool trust-boundary hardening

Date: 2026-09-28

## Problem

AI Workflow already marks retrieved repository/provider/memory content as
non-authoritative evidence and denies model requests for network access, secrets,
repository activation, provider selection, lane changes, and verification bypass.

The remaining authorization gap is narrower but important: an allowlisted tool
was authorized by tool name alone. Structured model-supplied arguments were
bound into the request digest, but were not independently checked for authority
smuggling or repository/path scope.

An indirect prompt injection could therefore try to keep the approved tool name
while placing a shell command, external URL, secret request, repository escape,
or excessive graph depth inside nested tool arguments.

## Research basis refreshed 2026-09-28

### Model Context Protocol — tool annotations and trust

The MCP project states that tool annotations are hints, not enforcement. Clients
must treat annotations from untrusted servers as untrusted, and deterministic
authorization/runtime controls must provide actual safety guarantees.

https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/

The MCP Skills extension similarly states that server-provided instructional
content is untrusted and must not cause implicit host-side execution.

https://skills.extensions.modelcontextprotocol.io/specification/stable/skills

### OWASP prompt injection and agent security

OWASP recommends treating models as untrusted users, applying least privilege,
validating tool calls against original user intent, isolating privileged tools,
and enforcing restrictions at the execution layer rather than relying on prompt
instructions.

https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

OWASP's MCP tool-poisoning guidance specifically calls out the risk of external
tool output driving trusted internal tools, secret access, or exfiltration.

https://community.owasp.org/attacks/MCP_Tool_Poisoning

### 2026 indirect-prompt-injection evidence

Large-scale 2026 red-team results show that indirect prompt injection remains a
practical failure mode across tool-using and coding agents, including attempts
that conceal compromise from the user.

https://arxiv.org/abs/2603.15714

AttriGuard argues for action-level attribution: a sensitive action should remain
supported by the user's task rather than being caused by untrusted observations.

https://arxiv.org/abs/2603.10749

## Design

PR-31 upgrades the machine-readable policy to `capability-v2`.

The authorization policy is still built only from code-owned state:

- deterministic lane/risk;
- orchestration-generated tool allowlist;
- system-assigned evidence repository identities;
- orchestration graph-depth budget;
- a SHA-256 digest of the original task text.

The raw task text is not persisted in the authorization policy.

### Tool execution now requires both name and scope

For an allowlisted tool, the gate rejects:

- network/secret/provider/lane/verification fields smuggled into the tool request;
- nested privileged parameter keys such as `command`, `url`,
  `secret_name`, `provider_id`, or `skip_verification`;
- repository IDs outside the active repository set;
- ambiguous multi-repository calls without an explicit repository ID;
- absolute paths, URI paths, Windows drive paths, or `..` traversal;
- graph depth beyond the orchestration budget;
- over-deep/over-large structured parameters.

### Evidence authority remains zero

Evidence envelopes now explicitly serialize false authority for:

- instructions;
- tools;
- policy;
- repository activation;
- network access;
- secret access;
- durable-memory write;
- verification bypass.

These fields are code-owned. Provider/repository content cannot set them.

## Important limitations

- Deterministic parameter controls do not solve semantic prompt injection inside
  arbitrary free-text query strings.
- The policy protects AI Workflow-owned authorization. Host/MCP/runtime
  integrations must actually call the gate before privileged execution.
- Relative path checks prevent scope escape but are not a filesystem sandbox.
- Task digests bind audit records to original intent without semantically
  proving that every allowed read-only query is necessary.
- Tool metadata from an untrusted server remains informational only.

## Acceptance criteria

- allowlisted tools with safe scoped parameters still work;
- nested capability smuggling is denied;
- repository scope cannot be widened by model/evidence content;
- multi-repository actions require explicit scope;
- absolute/traversal paths are denied;
- graph depth cannot exceed the control-plane budget;
- parameter structure has deterministic limits;
- poisoned external evidence cannot grant tool/network/secret authority;
- engine and Workflow API expose `capability-v2` bound to the original task;
- full tests/security/CodeQL/package/container/binary matrix passes before the
  PR is declared merge-ready.
