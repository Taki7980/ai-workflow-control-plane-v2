# Skill / Provider Routing

The control plane owns routing; skills execute inside the chosen lane.

- Answer: no methodology skill by default.
- Small: native execution unless the user explicitly requests another workflow.
- Full: prefer Superpowers when detected; otherwise native Plan → Build → Review.
- Structural/multi-hop context: use Code Review Graph when detected and justified.
- Noisy shell output: RTK when detected; deterministic compressor otherwise.

Do not stack multiple orchestration frameworks for the same task.
