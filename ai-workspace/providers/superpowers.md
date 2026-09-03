# Superpowers Provider

Superpowers is optional and is never vendored or installed automatically by this project.

For Full-lane work:
- If an implementation plan is approved and subagents are available, prefer `subagent-driven-development`.
- Use `executing-plans` when sequential execution is the appropriate fallback.
- Pass only the bounded handoff/context packet; do not duplicate full conversation history.
- Preserve Superpowers' own TDD/review gates rather than reimplementing them in AI Workflow.

`doctor` reports whether a recognizable local/user Superpowers skill installation is detected.
