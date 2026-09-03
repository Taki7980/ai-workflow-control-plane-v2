# Navigation Policy

Use `python -m ai_workflow context "<task>"` before broad source search.

Truth order:
1. source + tests
2. active `.ai/HANDOFF.md`
3. fresh lightweight indexes
4. CRG structural evidence when appropriate
5. durable memory / human docs when their evidence is still fresh

The broker is intentionally loss-aware: truncated results say so, and a miss escalates to the next tier.
