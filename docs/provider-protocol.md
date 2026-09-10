# Retriever provider protocol and trust boundary

Configured executables are trusted only as executable choices; returned repository/context data remains untrusted evidence. Providers receive one UTF-8 JSON request on stdin and may return an `items` object, JSON array, or JSONL. File/path metadata is confined to the workspace.

Every command provider runs without a shell, with an explicit timeout, hard stdout byte limit, stderr excluded from context ingestion, and a restricted environment. Credentials are inherited only by explicitly allowlisted variable name. The native async port uses `asyncio.create_subprocess_exec`; cancellation kills and reaps the child. Existing synchronous APIs remain compatible.

`RetrievalRequest`, `ProviderResult`, synchronous `Retriever`, and asynchronous `AsyncRetriever` define the typed boundary. `retrieval_adapters` includes local, CRG, memory, semantic-command, and external-command adapters.

A provider may declare `version` plus `semantics`: `deterministic`, `cacheable`, `idempotent`, `side_effecting`, and `retryable`. Missing declarations are conservative: version `unknown`, deterministic false, cacheable false. Scores never imply cacheability. Cache identity also contains provider version, retrieval-policy version, deterministic workspace identity, and canonical request parameters.

Structured failures remain `configuration`, `launch`, `timeout`, `output_limit`, `exit`, `empty_output`, `invalid_payload`, and `not_configured`. String commands remain supported; argv arrays are preferred for portable quoting.
