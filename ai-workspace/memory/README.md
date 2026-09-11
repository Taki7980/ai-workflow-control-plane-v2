# Legacy memory import

Operational durable memory is not stored in this repository.

AI Workflow stores the SQLite memory database in a user-owned application-state directory outside the project. Files placed in this directory are treated as untrusted legacy input and are never imported automatically.

To deliberately migrate a reviewed JSONL file:

```bash
ai-workflow memory import --trusted ai-workspace/memory/memory.jsonl
```

Do not commit operational memory, credentials, prompts, private source excerpts, or personal data here.
