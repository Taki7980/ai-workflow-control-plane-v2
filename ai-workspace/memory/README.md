# Runtime memory

This directory is reserved for local AI Workflow runtime memory.

Operational memory files are intentionally excluded from source control and Docker build context. A repository-local `memory.jsonl` is treated as untrusted data and is never imported automatically.

Legacy JSONL can be imported only through an explicit operator-selected import using `SQLiteMemoryStore.import_jsonl(path)` after the source has been reviewed and trusted.

Do not commit prompts, retrieved context, credentials, personal data, or generated memory databases to this directory.
