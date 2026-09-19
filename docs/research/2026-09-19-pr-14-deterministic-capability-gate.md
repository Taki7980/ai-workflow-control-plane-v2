# PR-14 — Deterministic Post-LLM Capability Gate

Date: 2026-09-19

## Problem

PR-13 made retrieved evidence typed and explicitly non-authoritative. The next
required boundary is the action side of the system:

```text
untrusted evidence
    -> LLM reasoning
    -> proposed privileged action
    -> deterministic authorization
    -> executor
```

A model must not be able to convert prompt-injected repository/provider content
into tool, network, secret, provider, repository, safety-policy, or
verification authority.

AI Workflow currently prepares retrieval and orchestration contracts. It does
not own a general arbitrary-tool executor. PR-14 therefore implements the
authorization contract that an executor must call instead of pretending an
executor exists.

## Research basis

### CaMeL — Defeating Prompt Injections by Design

https://arxiv.org/abs/2503.18813

CaMeL places a protective system layer around the model, separates trusted
control flow from untrusted data flow, and uses capabilities to block
unauthorized flows. PR-14 applies that architectural principle at the proposed
action boundary.

### AgentArmor

https://arxiv.org/abs/2508.01249

AgentArmor treats runtime traces as structured programs, attaches security
properties to data/tools, and performs policy checking independent of natural
language reasoning. PR-14 similarly makes authorization a typed deterministic
check over a structured request.

### GitInject

https://arxiv.org/abs/2606.09935

GitInject evaluates real AI-powered GitHub workflows and finds important
failures caused by infrastructure permissions/configuration, not merely model
behavior. This supports enforcing authority outside the LLM in a coding
workflow.

### OWASP AI Agent Security Cheat Sheet

https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

Relevant guidance:
- least-privilege tool scopes
- explicit authorization for sensitive operations
- separate decision-making from execution
- bind approval to the exact action
- fail closed on policy/authorization failure
- do not rely solely on model output for authorization
- retain structured decision metadata

### OWASP LLM Prompt Injection Prevention

https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

Relevant guidance:
- validate tool calls against permissions/session context
- restrict tool access by least privilege
- screen proposed actions against trusted intent rather than untrusted
  intermediate context
- prefer deterministic checks for routine authorization paths

### NIST — Software and AI Agent Identity and Authorization

https://csrc.nist.gov/pubs/other/2026/02/05/accelerating-the-adoption-of-software-and-ai-agent/ipd

NIST explicitly identifies authorization controls as necessary when agents gain
access to diverse data, tools, and applications.

## Implemented policy

`ModelCapabilityPolicy` is created from code-owned pre-LLM state:

- classified lane and risk
- control-plane orchestration plan
- exact CRG tool allowlist
- mandatory verification count
- repository identities from the PR-13 evidence envelope

Evidence text is never consulted to create permission.

## Capabilities

The gate produces deterministic decisions for:

- `tool_execution`
- `provider_selection`
- `repository_activation`
- `network_access`
- `secret_access`
- `safety_lane_change`
- `skip_verification`

Default behavior:

| Capability | Model policy |
|---|---|
| Tool execution | allow only exact precomputed CRG tool names |
| Provider selection | control-plane-owned; deny |
| Repository activation | operator-owned; deny |
| Network access | trusted-runtime grant required; deny by default |
| Secret access | trusted-runtime grant required; deny by default |
| Safety-lane change | control-plane-owned; deny |
| Skip verification | deny while verification is required |

No repository configuration can expand these permissions in PR-14.

## Exact-action binding

Every `ModelActionRequest` gets a canonical SHA-256 request digest over:

- capability
- tool/provider/repository/host/secret/lane target
- structured parameters
- cited evidence IDs

This gives the caller a stable exact-action identity for audit and future
short-lived authorization/replay controls.

## Evidence behavior

A model may cite evidence IDs. The gate verifies that all cited IDs exist.

- unknown evidence ID -> fail closed
- known evidence -> may support reasoning, but does not grant authority
- malicious evidence saying `trusted_system` or `admin` has no effect

## API

`WorkflowResult` now exposes:

```python
result.capability_policy
result.authorize_model_action(request)
```

The same policy is emitted in workflow diagnostics as
`authorization_policy` and recorded in the run journal when journaling is
enabled.

## Scope boundary

PR-14 does not:
- invent a shell/tool executor
- grant network or secret access
- move operator-owned repository activation into the model
- allow the model to downgrade safety lanes
- allow verification bypass
- add a runtime dependency

Future execution adapters must call this boundary before privileged effects.

## Regression contract

The tests prove:

1. only precomputed tool names can execute;
2. arbitrary shell-style tool requests fail closed;
3. provider selection is model-denied;
4. repository activation is model-denied;
5. network access is denied without trusted-runtime authority;
6. secret access is denied without trusted-runtime authority;
7. safety-lane changes are model-denied;
8. required verification cannot be skipped;
9. malicious evidence cannot grant any of the above;
10. unknown evidence references fail closed;
11. authorization request digests are stable and parameter-bound;
12. the public workflow API exposes the same deterministic gate.
