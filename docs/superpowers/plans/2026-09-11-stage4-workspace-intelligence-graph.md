# Stage 4 Workspace Intelligence Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, evidence-backed cross-repository workspace graph that augments Stage 3 retrieval with bounded structural expansion while preserving one global context budget.

**Architecture:** Persist portable graph nodes/edges under the existing single `ai-workspace/generated/` directory. Build graph structure from static repository evidence only, then seed and expand it after Stage 3 repository selection and before the final global context pack. Graph failures fail open to the existing Stage 3 retrieval path.

**Tech Stack:** Python 3.10+, standard library only at runtime, unittest, Ruff, Mypy, existing JSONL/index/state utilities.

**Spec:** `docs/superpowers/specs/2026-09-11-stage4-workspace-intelligence-graph-design.md`

## Global Constraints

- No external graph database.
- No required embeddings or LLM/API calls.
- No LLM-generated graph topology.
- No runtime package-manager execution or repository code import.
- Graph state contains no absolute checkout paths or credentials.
- Only active repositories participate in persisted graph state or traversal.
- Graph expansion defaults: max_hops=2, max_nodes=24, max_edges=40, max_context_chars=3000, min_edge_confidence=0.8.
- Graph context shares the existing parent `ContextBudget.context_chars`; it is never additive.
- Existing benchmark baseline and tolerances remain unchanged.
- Supported compatibility remains Ubuntu Python 3.10-3.14, Windows Python 3.14, macOS Python 3.14.

---

### Task 1: Portable graph model and persistence

**Files:**
- Create: `ai_workflow/workspace_graph.py`
- Create: `tests/test_workspace_graph.py`

**Interfaces:**
- Produces:
  - `GraphNode`
  - `GraphEdge`
  - `WorkspaceGraph`
  - `node_id(...)`
  - `edge_id(...)`
  - `graph_fingerprint(...)`
  - `save_workspace_graph(root, graph, state)`
  - `load_workspace_graph(root) -> tuple[WorkspaceGraph | None, dict]`

- [ ] **Step 1: Write failing identity/persistence tests**

```python
def test_graph_identity_is_portable_and_deterministic():
    a = node_id("file", "repo-a", "src/api.py", "")
    b = node_id("file", "repo-a", "src/api.py", "")
    assert a == b

def test_graph_round_trip_uses_stable_order(tmp_path):
    graph = WorkspaceGraph(nodes=(...), edges=(...))
    save_workspace_graph(tmp_path, graph, {"schema_version": 1})
    loaded, state = load_workspace_graph(tmp_path)
    assert loaded == graph
    assert state["schema_version"] == 1
```

- [ ] **Step 2: Run red phase**

Run:
```bash
python -m unittest tests.test_workspace_graph -v
```

Expected: FAIL because `ai_workflow.workspace_graph` does not exist.

- [ ] **Step 3: Implement immutable model and SHA-256 IDs**

```python
@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    repository_id: str
    repository_path: str
    path: str
    symbol: str
    label: str
    fingerprint: str
    evidence: str

@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str
    source_repository_id: str
    target_repository_id: str
    evidence_path: str
    evidence_line: int | None
    extractor: str
    confidence: float
    fingerprint: str

@dataclass(frozen=True)
class WorkspaceGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
```

IDs use canonical UTF-8 JSON plus SHA-256. Save JSONL in deterministic sort order and write state atomically using existing IO utilities.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_workspace_graph -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ai_workflow/workspace_graph.py tests/test_workspace_graph.py
git commit -m "feat: add portable workspace graph model"
```

---

### Task 2: Deterministic graph builder and static extractors

**Files:**
- Create: `ai_workflow/workspace_graph_builder.py`
- Create: `tests/test_workspace_graph_builder.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `WorkspaceGraph`, Stage 3 repository candidates/fingerprints.
- Produces:
  - `build_workspace_graph(workspace_root: Path, config: dict, *, force: bool = False) -> tuple[WorkspaceGraph, dict]`
  - `graph_status(workspace_root: Path, config: dict) -> dict`

- [ ] **Step 1: Write failing extractor tests**

Cover:
- active repositories only;
- deterministic repository/file nodes;
- `package.json` local `DEPENDS_ON`;
- `go.mod` local module dependency;
- Python/JS/TS/Go exact import relationships;
- endpoint-index `IMPLEMENTS_ENDPOINT`;
- literal route `CALLS_API`;
- deterministic `TESTS`;
- inactive repository exclusion;
- no absolute paths in serialized output;
- same inputs produce identical graph fingerprint.

Example:

```python
def test_local_package_dependency_creates_cross_repo_edge():
    graph, _ = build_workspace_graph(root, config, force=True)
    edges = [e for e in graph.edges if e.edge_type == "DEPENDS_ON"]
    assert any(e.source_repository_id == frontend_id and e.target_repository_id == shared_id for e in edges)
```

- [ ] **Step 2: Run red phase**

```bash
python -m unittest tests.test_workspace_graph_builder -v
```

Expected: FAIL because builder does not exist.

- [ ] **Step 3: Implement evidence extraction**

Use static text parsing only:

```python
_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_.]+)")
_JS_IMPORT = re.compile(r"(?:from\s+|require\()['\"]([^'\"]+)")
_HTTP_LITERAL = re.compile(r"['\"](/api/[A-Za-z0-9_./:{}-]+)['\"]")
```

Manifest package identity:
- package.json: `name`
- go.mod: first `module ...`
- pyproject.toml: `[project] name = "..."`

Resolve local package/import edges only on exact identity/prefix matches. Parse text files with size caps; never execute project code.

- [ ] **Step 4: Implement state reuse/invalidation**

State includes aggregate and per-repository fingerprints plus extractor version. If unchanged, load persisted graph. If changed, correctness-first rebuild is allowed for MVP; unchanged persisted fragments may be reused only when identity/fingerprint match exactly.

- [ ] **Step 5: Run tests**

```bash
python -m unittest tests.test_workspace_graph tests.test_workspace_graph_builder -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ai_workflow/workspace_graph_builder.py tests/test_workspace_graph_builder.py
git commit -m "feat: build deterministic workspace intelligence graph"
```

---

### Task 3: Bounded graph seed resolution and expansion

**Files:**
- Create: `ai_workflow/workspace_graph_retrieval.py`
- Create: `tests/test_workspace_graph_retrieval.py`

**Interfaces:**
- Produces:
  - `GraphRetrievalResult(items: tuple[ContextItem, ...], diagnostics: dict[str, Any])`
  - `retrieve_workspace_graph(graph, query, selected_repository_ids, *, symbol=None, endpoint=None, changed_files=(), seed_items=(), graph_fingerprint="", config=None) -> GraphRetrievalResult`

- [ ] **Step 1: Write failing traversal tests**

Cover:
- explicit endpoint seed reaches backend implementation from frontend route caller;
- max_hops stops third-hop expansion;
- max_nodes/max_edges are hard caps;
- inactive/unselected repository nodes are ignored;
- repeated runs return identical ordering;
- graph `ContextItem` provenance is portable;
- duplicate graph identity is deduped by node/edge identity, not text.

- [ ] **Step 2: Run red phase**

```bash
python -m unittest tests.test_workspace_graph_retrieval -v
```

Expected: FAIL.

- [ ] **Step 3: Implement deterministic seed matching**

Seed priority:
1. exact symbol;
2. exact normalized endpoint;
3. Stage 3 item path/symbol metadata;
4. changed-file path;
5. selected repository node.

- [ ] **Step 4: Implement bounded BFS and scoring**

```python
score = (
    4.0 * query_overlap
    + 3.0 * seed_match
    + 2.0 * changed_file_match
    + 2.0 * cross_repo_bonus
    + edge_confidence
    - 1.5 * distance
)
```

Tie-break:
```python
(-score, distance, repository_id, kind, path, node_id)
```

Only edges at or above configured confidence are traversed. Only repository IDs supplied by Stage 3 selection are eligible.

- [ ] **Step 5: Convert ranked nodes to bounded graph context**

Each `ContextItem(source="workspace_graph", ...)` includes graph node/edge IDs, distance, graph fingerprint, repository provenance, and evidence path. Stop at `max_context_chars`.

- [ ] **Step 6: Run tests and commit**

```bash
python -m unittest tests.test_workspace_graph_retrieval -v
git add ai_workflow/workspace_graph_retrieval.py tests/test_workspace_graph_retrieval.py
git commit -m "feat: add bounded workspace graph retrieval"
```

---

### Task 4: Config and Stage 3 retrieval integration

**Files:**
- Modify: `ai_workflow/config.py`
- Modify: `ai_workflow/workspace_retrieval.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_workspace_retrieval.py`

**Interfaces:**
- Adds `workspace.graph` defaults and validation.
- Workspace retrieval diagnostics gain optional `workspace_graph`.

- [ ] **Step 1: Write failing config tests**

```python
def test_stage4_graph_defaults():
    graph = default_config()["workspace"]["graph"]
    assert graph == {
        "enabled": True,
        "max_hops": 2,
        "max_nodes": 24,
        "max_edges": 40,
        "max_context_chars": 3000,
        "min_edge_confidence": 0.8,
        "build_on_demand": True,
    }
```

Add boundary rejection tests for each numeric field and booleans.

- [ ] **Step 2: Write failing workspace integration tests**

Mock graph build/retrieval and verify:
- graph retrieval receives Stage 3 selected repository IDs;
- graph items enter the same final pack;
- final characters never exceed parent context;
- graph exception leaves Stage 3 items intact and emits diagnostic status;
- disabled graph performs no graph build/retrieval.

- [ ] **Step 3: Run red phase**

```bash
python -m unittest tests.test_config tests.test_workspace_retrieval -v
```

- [ ] **Step 4: Implement defaults/validation**

Add `workspace.graph` to `_DEFAULT_CONFIG`. Validation enforces exact bounds from the spec.

- [ ] **Step 5: Integrate graph augmentation**

After Stage 3 repository retrieval has produced portable items:
1. build/load graph when enabled;
2. call graph retrieval with selected repository IDs and Stage 3 items as seeds;
3. append graph items to the same global candidate list;
4. run one final cap at `budget.context_chars`;
5. store diagnostics under `workspace_graph`.

Any graph exception is caught at this optional boundary only.

- [ ] **Step 6: Run tests and commit**

```bash
python -m unittest tests.test_config tests.test_workspace_retrieval tests.test_workspace_graph_retrieval -v
git add ai_workflow/config.py ai_workflow/workspace_retrieval.py tests/test_config.py tests/test_workspace_retrieval.py
git commit -m "feat: integrate workspace graph with stage3 retrieval"
```

---

### Task 5: Graph CLI

**Files:**
- Modify: `ai_workflow/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Adds:
  - `ai-workflow graph build`
  - `ai-workflow graph status`

- [ ] **Step 1: Write failing CLI tests**

Verify deterministic JSON keys and that status does not execute repository code.

```python
packet = self.run_cli("graph", "status")
self.assertIn("status", packet)
self.assertIn("graph_fingerprint", packet)
```

- [ ] **Step 2: Run red phase**

```bash
python -m unittest tests.test_cli -v
```

- [ ] **Step 3: Implement handlers/parser**

```python
def cmd_graph_build(args):
    graph, state = build_workspace_graph(_root(args), load_config(_root(args)), force=True)
    _json({...})

def cmd_graph_status(args):
    _json(graph_status(_root(args), load_config(_root(args))))
```

Add `graph` subparser with required `build|status`.

- [ ] **Step 4: Run tests and commit**

```bash
python -m unittest tests.test_cli -v
git add ai_workflow/cli.py tests/test_cli.py
git commit -m "feat: expose workspace graph cli"
```

---

### Task 6: Graph benchmark metrics and adversarial fixture

**Files:**
- Create: `ai_workflow/workspace_graph_metrics.py`
- Modify: `ai_workflow/benchmark.py`
- Modify: `tests/test_benchmark_metrics.py`
- Create: `tests/test_workspace_graph_adversarial.py`

**Interfaces:**
- Produces:
  - `graph_node_recall_at_k(...)`
  - `cross_repo_edge_recall(...)`
  - `wrong_edge_rate(...)`
  - `structural_recall_at_k(...)`
  - `graph_context_yield(...)`

- [ ] **Step 1: Write failing metric tests**

Use explicit gold node/edge IDs and assert exact ratios including empty-label `None` behavior.

- [ ] **Step 2: Write 10-repository adversarial fixture test**

Generate repositories in a temporary directory with duplicate `service.py`, duplicate symbols/routes, one true frontend/backend API relation, local package dependency, deterministic test edge, and one inactive tempting repository.

Assertions:
- inactive repo produces no graph nodes;
- true cross-repo edge is present;
- wrong duplicate route does not create a cross-repo edge;
- graph output is deterministic after relocation.

- [ ] **Step 3: Run red phase**

```bash
python -m unittest tests.test_benchmark_metrics tests.test_workspace_graph_adversarial -v
```

- [ ] **Step 4: Implement pure metric helpers**

Metrics consume graph item/node/edge identities and return floats or `None` for unlabeled cases.

- [ ] **Step 5: Add benchmark integration**

When task JSON contains `gold_graph_nodes`, `gold_graph_edges`, or `gold_structural_evidence`, include graph metrics in that case and aggregate only labeled cases. Existing Stage 3 result fields and regression checker remain unchanged.

- [ ] **Step 6: Run tests and commit**

```bash
python -m unittest tests.test_benchmark_metrics tests.test_workspace_graph_adversarial -v
git add ai_workflow/workspace_graph_metrics.py ai_workflow/benchmark.py tests/test_benchmark_metrics.py tests/test_workspace_graph_adversarial.py
git commit -m "test: add workspace graph retrieval benchmarks"
```

---

### Task 7: Documentation, quality gates, and release verification

**Files:**
- Modify: `docs/multi-repo-workspace-registry.md`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- No runtime API changes.

- [ ] **Step 1: Document Stage 4**

Add a Stage 4 section covering graph files, evidence policy, commands, caps, provenance, inactive-repository behavior, and non-goals.

- [ ] **Step 2: Add graph modules to Ruff/Mypy focused gates**

Add:
```text
ai_workflow/workspace_graph.py
ai_workflow/workspace_graph_builder.py
ai_workflow/workspace_graph_retrieval.py
ai_workflow/workspace_graph_metrics.py
```

- [ ] **Step 3: Run complete verification**

```bash
python -m unittest discover -s tests -v
python -m compileall -q ai_workflow
ruff check --select E,F,UP,BLE,EXE ai_workflow/workspace_graph.py ai_workflow/workspace_graph_builder.py ai_workflow/workspace_graph_retrieval.py ai_workflow/workspace_graph_metrics.py
mypy --follow-imports=skip ai_workflow/workspace_graph.py ai_workflow/workspace_graph_builder.py ai_workflow/workspace_graph_retrieval.py ai_workflow/workspace_graph_metrics.py
python -m ai_workflow index
python -m ai_workflow doctor --strict
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json --output benchmark-result.json
python scripts/check_benchmark_regression.py benchmarks/baseline.json benchmark-result.json
```

Expected: every command succeeds; benchmark thresholds remain unchanged.

- [ ] **Step 4: Commit**

```bash
git add docs/multi-repo-workspace-registry.md .github/workflows/tests.yml
git commit -m "docs: finalize stage4 workspace graph"
```

- [ ] **Step 5: Verify exact final head through CI**

Required successful jobs:
- package-smoke
- quality
- benchmark-regression
- Ubuntu Python 3.10
- Ubuntu Python 3.11
- Ubuntu Python 3.12
- Ubuntu Python 3.13
- Ubuntu Python 3.14
- Windows Python 3.14
- macOS Python 3.14

- [ ] **Step 6: Open PR**

Head:
`research/stage4-workspace-intelligence-graph`

Base:
`research/stage3-multi-repo-retrieval`

PR title:
`feat: add Stage 4 workspace intelligence graph`

Do not merge automatically.
