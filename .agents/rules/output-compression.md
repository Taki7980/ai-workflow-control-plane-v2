# Output Compression

- Short output: keep direct.
- Noisy output: prefer RTK when installed.
- Otherwise: `python -m ai_workflow compress --file <log> --max-lines 80`.
- Exact evidence/debugging: bypass compression.
- Never report RTK output reduction as total model-token savings.
