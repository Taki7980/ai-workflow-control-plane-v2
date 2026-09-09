# Configuration migrations and typed access

The control plane continues to read JSON from `ai-workspace/config/control-plane.json`, but configuration parsing now has an explicit schema boundary.

## Current schema

The current supported schema version is `2`.

A normal version-2 file is validated exactly as supplied. Missing required sections, invalid values, or an omitted version are not silently repaired. This preserves the existing fail-closed setup behavior.

## Legacy migration

Explicit version-1 documents are upgraded in memory before validation:

```json
{
  "version": 1,
  "workspace": {"roots": ["backend"]}
}
```

The v1 values are recursively overlaid on the current v2 defaults and the resulting document receives `"version": 2`. Unknown extension keys are preserved.

Migration is pure: the input object is never mutated and loading a configuration does not rewrite the file on disk.

Unversioned configuration is intentionally not treated as v1. This avoids accidentally accepting malformed or partially written configuration files.

Future versions are rejected with an explicit error rather than being interpreted as v2.

## Typed API

New code can use:

```python
from ai_workflow.config import load_typed_config

config = load_typed_config(root)
print(config.version)
print(config.context["max_results_per_source"])
```

`ControlPlaneConfig` implements the mapping protocol, so `.get(...)`, indexing, iteration, and membership checks continue to work. Its nested mappings and sequences are recursively immutable.

Convenience properties are available for the common sections:

- `config.context`
- `config.execution`
- `config.workspace`
- `config.memory`
- `config.budgets`
- `config.models`

Use `config.to_dict()` when a detached mutable copy is required.

## Compatibility

`load_config(root)` remains available and still returns a normal mutable dictionary. Internally it passes through the same migration/validation boundary and then returns a detached copy.

Unknown fields survive typed parsing and `to_dict()` round trips so integrations can carry extension metadata without the core package needing to understand it.