# PR-13 — Typed Untrusted Evidence Envelope

Date: 2026-09-19

## Problem

AI Workflow already labels some retrieval provenance with a free-form `trust`
string, but the trust boundary is not typed and provider/repository metadata can
still travel beside retrieved text without an explicit machine-readable
authority contract.

For a coding agent this matters because source files, comments, documentation,
generated caches, durable memory, graph output, semantic provider output, and
external retriever output must all be treated as evidence rather than as
instructions.

## Research basis

### CaMeL — Defeating Prompt Injections by Design

https://arxiv.org/abs/2503.18813

CaMeL separates trusted control flow from untrusted data flow and uses
capability-oriented enforcement so untrusted retrieved data cannot become the
program's control authority.

### AgentArmor

https://arxiv.org/abs/2508.01249

AgentArmor attaches security properties to agent data/tool flows and performs
policy checking over structured runtime traces. PR-13 adopts the narrower idea
needed by this repository: explicit typed properties on every selected evidence
item.

### IterInject

https://arxiv.org/abs/2605.24659

Adaptive indirect prompt injection remains effective against tool-using agents,
including coding-agent targets. Static prompt wording alone is therefore not a
sufficient boundary.

### GitInject

https://arxiv.org/abs/2606.09935

GitInject demonstrates that AI-powered GitHub/CI workflows process attacker-
controlled repository/PR content while holding elevated permissions. The
important failures are architectural permission and configuration failures, not
only model failures.

### LivePI

https://arxiv.org/abs/2605.17986

LivePI evaluates indirect prompt injection in production-like tool environments.
Its results support defense in depth and pre-execution authorization rather than
depending on prompt resistance alone.

### OWASP and NIST guidance

- https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html
- https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition
- https://csrc.nist.gov/pubs/other/2026/02/05/accelerating-the-adoption-of-software-and-ai-agent/ipd

The common guidance is to treat external data as untrusted, separate data from
instructions, apply least privilege, and keep authorization outside the model.

## Implemented contract

Each final selected `ContextItem` now carries an `EvidenceEnvelope` with:

- `evidence_id`: stable SHA-256 identity over repository, source, kind,
  exact content digest, and bounded locator.
- `repository_id`: checkout-path-independent repository identity using the
  existing repository registry contract, with deterministic fallbacks.
- `kind`: code-owned broad evidence category.
- `content_sha256`: SHA-256 of the exact text exposed downstream, including
  post-truncation content.
- `trust_class`: code-owned origin class. No retrieved evidence class is
  trusted authority.
- `authority`: explicit booleans for instruction, tool, policy, and
  repository-activation authority. All are false in PR-13.
- `provenance`: bounded system-owned provenance. Provider/repository claims
  cannot override trust, retriever identity, or authority.

The envelope is attached after final selection/truncation so identity always
matches the exact downstream payload.

## Compatibility

- Existing `ContextItem(...)` constructors remain valid.
- Existing `ContextItem.to_dict()` output is unchanged when no envelope is
  attached.
- Ranking, BM25/RRF/MMR, selector behavior, budgets, routing, provider
  scheduling, CRG/SCIP behavior, and learning policy are unchanged.
- No runtime dependency is added.

## Security boundary

PR-13 identifies evidence and makes its lack of authority explicit.

It does **not** yet implement the post-LLM action/capability enforcement layer.
That is intentionally PR-14, which can consume this typed authority contract to
reject tool/network/secret/policy/repository-activation requests that originate
from non-authoritative evidence.

## Required regression properties

1. Malicious repository text that says it is trusted remains untrusted.
2. External provider provenance cannot claim system/admin authority.
3. Evidence identity is stable for identical repository/content/location.
4. Content changes change evidence identity.
5. The content digest matches the exact final text after truncation.
6. Existing routing and algorithm policy remain code-owned.
