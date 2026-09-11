from __future__ import annotations
import copy
import json
from pathlib import Path, PureWindowsPath
from typing import Any

from .token_estimator import CharacterTokenEstimator, TokenEstimator

DEFAULT_RELATIVE = Path("ai-workspace/config/control-plane.json")
CURRENT_CONFIG_VERSION = 2
REQUIRED_SECTIONS = ("budgets", "classifier", "context", "workspace", "execution", "handoff", "memory", "models")

_DEFAULT_CONFIG = {
    "version": 2,
    "budgets": {
        "answer": {"estimated_tokens": 1200, "output_tokens": 450},
        "small": {"estimated_tokens": 2500, "output_tokens": 700},
        "full": {"estimated_tokens": 6000, "output_tokens": 1200},
    },
    "classifier": {
        "high_risk_keywords": ["auth", "authentication", "authorization", "security", "payment", "billing", "migration", "schema", "database", "delete data", "destructive", "concurrency", "race condition", "deploy", "production", "public api", "contract change", "permission", "credential", "secret"],
        "full_keywords": ["refactor", "architecture", "multi-file", "cross-cutting", "end-to-end", "redesign", "performance", "distributed", "integration", "implement feature"],
        "answer_keywords": ["explain", "what is", "how does", "why does", "compare", "difference", "where is", "show me", "understand"],
        "small_keywords": ["rename", "typo", "copy change", "small fix", "one-line", "one line", "adjust", "update text"],
    },
    "context": {
        "max_results_per_source": 6,
        "source_shares": {"hot_cache": 0.15, "lightweight": 0.3, "crg": 0.4, "source_fallback": 0.15},
        "crg": {
            "mode": "auto", "min_lane": "full",
            "structural_keywords": ["caller", "callee", "dependency", "dependents", "impact", "blast radius", "flow", "architecture", "tests for", "refactor", "what breaks", "affected"],
            "min_source_files": 250, "changed_files_threshold": 3,
        },
        "semantic": {
            "mode": "auto", "provider_id": "", "command": "",
            "timeout_seconds": 8, "max_results": 6,
            "max_output_bytes": 8388608, "env_allowlist": [],
        },
        "external_retrievers": [],
        "sufficiency": {"threshold": 0.72},
        "adaptive_budget": {"enabled": True, "high_sufficiency_fraction": 0.45, "medium_sufficiency_fraction": 0.7, "minimum_chars": 900},
        "selector": {"enabled": True, "tight_budget_fraction": 0.3, "mandatory_structural_evidence": True, "max_selector_candidates": 200},
        "telemetry": {"mode": "mutations"},
        "learning": {
            "mode": "off",
            "kill_switch": False,
            "exploration_probability": 0.05,
            "allowed_risks": ["low"],
            "eligible_arms": [
                "adaptive_math",
                "source_rank",
                "bm25_rank",
                "rrf_only",
                "rrf_mmr_050",
                "rrf_mmr_075",
                "rrf_mmr_090",
            ],
        },
        "deployment": {
            "enabled": False,
            "state_path": (
                "ai-workspace/generated/learning/deployment/active.json"
            ),
            "signing_key_env": "AI_WORKFLOW_POLICY_SIGNING_KEY",
            "auto_rollback": True,
            "incident_bundles": True,
        },
        "production": {
            "enabled": False,
            "sqlite_path": (
                "ai-workspace/generated/learning/production/events.sqlite3"
            ),
            "busy_timeout_ms": 5000,
        },
        "targeted_search": {"max_matches": 12, "max_file_bytes": 500000},
    },
    "workspace": {
        "roots": [],
        "max_roots": 4,
        "registry": "ai-workspace/config/repositories.json",
        "discovery": {"max_depth": 3, "require_acceptance": True},
    },
    "execution": {
        "prefer_superpowers_for_full": True,
        "native_fallback": True,
        "superpowers": {"mode": "auto"},
        "orchestration_budget": {"max_agent_slots": 4, "max_crg_calls": 6, "max_graph_depth": 3, "review_passes": 2, "verification_passes": 2},
    },
    "handoff": {"max_lines": 30},
    "memory": {"max_results": 5, "minimum_confidence": 0.55},
    "models": {"answer": "fast", "small": "fast", "full_medium": "standard", "full_high": "capable"},
}

_DEFAULT_TOKEN_ESTIMATOR = CharacterTokenEstimator()


def default_config() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT_CONFIG)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Return a migrated detached config without mutating caller input.

    Current v2 inputs are not default-filled: they retain the existing strict
    validation boundary. Explicit v1 inputs are upgraded by overlaying their
    values onto v2 defaults. Unversioned inputs remain unversioned so the
    existing fail-closed validation behavior is preserved.
    """

    if not isinstance(data, dict):
        raise ValueError("control-plane config must be a JSON object")
    raw = copy.deepcopy(data)
    version = raw.get("version")
    if version is None:
        return raw
    if version == 1:
        raw.pop("version", None)
        migrated = _deep_merge(default_config(), raw)
        migrated["version"] = CURRENT_CONFIG_VERSION
        return migrated
    if version == CURRENT_CONFIG_VERSION:
        return raw
    if isinstance(version, int) and version > CURRENT_CONFIG_VERSION:
        raise ValueError(f"config version {version} is newer than supported version {CURRENT_CONFIG_VERSION}")
    raise ValueError(f"unsupported control-plane config version: {version}")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _fraction(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return float(value)


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{name} must be an array of non-empty strings")
    return value


def _provider_command(value: Any, name: str) -> None:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{name} must not be blank")
        return
    if isinstance(value, list) and value and all(isinstance(part, str) and part for part in value):
        return
    raise ValueError(f"{name} must be a non-empty string or argv array")


def validate_config(data: dict[str, Any]) -> None:
    if data.get("version") != CURRENT_CONFIG_VERSION:
        raise ValueError("unsupported control-plane config version")
    for section in REQUIRED_SECTIONS:
        if not isinstance(data.get(section), dict):
            raise ValueError(f"missing required section: {section}")
    for lane in ("answer", "small", "full"):
        budget = data["budgets"].get(lane)
        if not isinstance(budget, dict):
            raise ValueError(f"missing required budget: {lane}")
        _positive_int(budget.get("estimated_tokens"), f"budgets.{lane}.estimated_tokens")
        _positive_int(budget.get("output_tokens"), f"budgets.{lane}.output_tokens")

    shares = data["context"].get("source_shares")
    if not isinstance(shares, dict) or not shares:
        raise ValueError("context.source_shares must be a non-empty object")
    for name, value in shares.items():
        _fraction(value, f"source share {name}")
    if sum(float(value) for value in shares.values()) > 1.000001:
        raise ValueError("source shares must sum to at most 1")

    for key in ("crg", "targeted_search", "semantic", "sufficiency", "adaptive_budget", "selector", "telemetry"):
        if not isinstance(data["context"].get(key), dict):
            raise ValueError(f"missing required section: context.{key}")
    retrievers = data["context"].get("external_retrievers", [])
    if not isinstance(retrievers, list):
        raise ValueError("context.external_retrievers must be an array")
    for index, spec in enumerate(retrievers):
        prefix = f"context.external_retrievers[{index}]"
        if not isinstance(spec, dict) or not str(spec.get("name", "")).strip():
            raise ValueError(f"{prefix} requires a non-empty name")
        provider_id = str(spec.get("provider_id") or "").strip()
        command = spec.get("command")
        has_command = command not in (None, "", [])
        if not provider_id and not has_command:
            raise ValueError(f"{prefix} requires provider_id")
        if provider_id and has_command:
            raise ValueError(
                f"{prefix} may not combine provider_id with repository command"
            )
        if provider_id and spec.get("env_allowlist") not in (None, [], ()):
            raise ValueError(
                f"{prefix} may not define env_allowlist with provider_id"
            )
        if has_command:
            _provider_command(command, f"{prefix}.command")
        intents = _string_list(spec.get("intents", ["all"]), f"{prefix}.intents")
        if not {str(x).lower() for x in intents}.issubset({"exact", "semantic", "structural", "mixed", "all"}):
            raise ValueError(f"{prefix}.intents contains unsupported values")
        _positive_int(int(spec.get("timeout_seconds", 8)), f"{prefix}.timeout_seconds")
        _positive_int(int(spec.get("max_output_bytes", 8388608)), f"{prefix}.max_output_bytes")
        _string_list(spec.get("env_allowlist", []), f"{prefix}.env_allowlist")

    semantic = data["context"]["semantic"]
    if semantic.get("mode", "auto") not in {"auto", "on", "off"}:
        raise ValueError("context.semantic.mode must be auto, on, or off")
    semantic_provider_id = str(semantic.get("provider_id") or "").strip()
    semantic_command = semantic.get("command")
    has_semantic_command = semantic_command not in (None, "", [])
    if semantic_provider_id and has_semantic_command:
        raise ValueError(
            "context.semantic may not combine provider_id with repository command"
        )
    if semantic_provider_id and semantic.get("env_allowlist") not in (None, [], ()):
        raise ValueError(
            "context.semantic may not define env_allowlist with provider_id"
        )
    if has_semantic_command:
        _provider_command(semantic_command, "context.semantic.command")
    _positive_int(int(semantic.get("timeout_seconds", 0)), "context.semantic.timeout_seconds")
    _positive_int(int(semantic.get("max_results", 0)), "context.semantic.max_results")
    _positive_int(int(semantic.get("max_output_bytes", 8388608)), "context.semantic.max_output_bytes")
    _string_list(semantic.get("env_allowlist", []), "context.semantic.env_allowlist")
    _fraction(data["context"]["sufficiency"].get("threshold"), "context.sufficiency.threshold")
    adaptive = data["context"]["adaptive_budget"]
    _fraction(adaptive.get("high_sufficiency_fraction"), "context.adaptive_budget.high_sufficiency_fraction")
    _fraction(adaptive.get("medium_sufficiency_fraction"), "context.adaptive_budget.medium_sufficiency_fraction")
    _positive_int(adaptive.get("minimum_chars"), "context.adaptive_budget.minimum_chars")
    selector = data["context"]["selector"]
    if not isinstance(selector.get("enabled", True), bool):
        raise ValueError("context.selector.enabled must be boolean")
    _fraction(selector.get("tight_budget_fraction"), "context.selector.tight_budget_fraction")
    if not isinstance(selector.get("mandatory_structural_evidence", True), bool):
        raise ValueError("context.selector.mandatory_structural_evidence must be boolean")
    _positive_int(selector.get("max_selector_candidates", 200), "context.selector.max_selector_candidates")
    telemetry = data["context"]["telemetry"]
    if telemetry.get("mode", "mutations") not in {"off", "mutations", "all"}:
        raise ValueError("context.telemetry.mode must be off, mutations, or all")
    trusted_runtime_fields = {
        "otlp_endpoint",
        "otlp_allowed_hosts",
        "otlp_headers_env",
        "otlp_headers",
        "store_task_text",
        "include_task_text",
        "export_timeout_seconds",
    }
    for field in sorted(trusted_runtime_fields):
        if field in telemetry:
            raise ValueError(
                f"context.telemetry.{field} is trusted runtime configuration "
                "and must not appear in project config"
            )

    learning = data["context"].get("learning")
    if learning is not None:
        if not isinstance(learning, dict):
            raise ValueError("context.learning must be an object")
        if learning.get("mode", "off") not in {"off", "observe", "explore"}:
            raise ValueError("context.learning.mode must be off, observe, or explore")
        if not isinstance(learning.get("kill_switch", False), bool):
            raise ValueError("context.learning.kill_switch must be boolean")
        _fraction(
            learning.get("exploration_probability", 0.05),
            "context.learning.exploration_probability",
        )
        allowed_risks = _string_list(
            learning.get("allowed_risks", ["low"]),
            "context.learning.allowed_risks",
        )
        if not {value.lower() for value in allowed_risks}.issubset({"low"}):
            raise ValueError(
                "context.learning.allowed_risks may only contain low"
            )
        eligible_arms = _string_list(
            learning.get("eligible_arms", ["adaptive_math"]),
            "context.learning.eligible_arms",
        )
        safe_arms = {
            "adaptive_math",
            "source_rank",
            "bm25_rank",
            "rrf_only",
            "rrf_mmr_050",
            "rrf_mmr_075",
            "rrf_mmr_090",
        }
        if not set(eligible_arms).issubset(safe_arms):
            raise ValueError(
                "context.learning.eligible_arms contains an unsafe or unknown arm"
            )
        if "adaptive_math" not in eligible_arms:
            raise ValueError(
                "context.learning.eligible_arms must include adaptive_math"
            )

    deployment = data["context"].get("deployment")
    if deployment is not None:
        if not isinstance(deployment, dict):
            raise ValueError("context.deployment must be an object")
        if not isinstance(deployment.get("enabled", False), bool):
            raise ValueError("context.deployment.enabled must be boolean")
        if not isinstance(deployment.get("auto_rollback", True), bool):
            raise ValueError(
                "context.deployment.auto_rollback must be boolean"
            )
        if not isinstance(
            deployment.get("incident_bundles", True),
            bool,
        ):
            raise ValueError(
                "context.deployment.incident_bundles must be boolean"
            )
        if (
            deployment.get("enabled", False)
            and not deployment.get("auto_rollback", True)
        ):
            raise ValueError(
                "enabled deployment requires automatic rollback"
            )
        state_path = deployment.get(
            "state_path",
            "ai-workspace/generated/learning/deployment/active.json",
        )
        if not isinstance(state_path, str) or not state_path.strip():
            raise ValueError(
                "context.deployment.state_path must be a relative path"
            )
        candidate = Path(state_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                "context.deployment.state_path must stay inside project root"
            )
        signing_key_env = deployment.get(
            "signing_key_env",
            "AI_WORKFLOW_POLICY_SIGNING_KEY",
        )
        if (
            not isinstance(signing_key_env, str)
            or not signing_key_env.strip()
        ):
            raise ValueError(
                "context.deployment.signing_key_env must be non-empty"
            )

    production = data["context"].get("production")
    if production is not None:
        if not isinstance(production, dict):
            raise ValueError("context.production must be an object")
        if not isinstance(production.get("enabled", False), bool):
            raise ValueError("context.production.enabled must be boolean")
        sqlite_path = production.get(
            "sqlite_path",
            "ai-workspace/generated/learning/production/events.sqlite3",
        )
        if not isinstance(sqlite_path, str) or not sqlite_path.strip():
            raise ValueError(
                "context.production.sqlite_path must be a relative path"
            )
        sqlite_candidate = Path(sqlite_path)
        if sqlite_candidate.is_absolute() or ".." in sqlite_candidate.parts:
            raise ValueError(
                "context.production.sqlite_path must stay inside project root"
            )
        _positive_int(
            production.get("busy_timeout_ms", 5000),
            "context.production.busy_timeout_ms",
        )

    roots = data["workspace"].get("roots", [])
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        raise ValueError("workspace.roots must be an array of paths")
    _positive_int(data["workspace"].get("max_roots"), "workspace.max_roots")
    registry = data["workspace"].get("registry", "ai-workspace/config/repositories.json")
    if not isinstance(registry, str) or not registry.strip():
        raise ValueError("workspace.registry must be a non-empty path")
    registry_path_value = Path(registry)
    registry_windows = PureWindowsPath(registry)
    if (
        registry_path_value.is_absolute()
        or registry_windows.is_absolute()
        or registry_windows.drive
        or ".." in registry_path_value.parts
        or ".." in registry_windows.parts
    ):
        raise ValueError(
            "workspace.registry must be a relative path inside the project root"
        )
    discovery = data["workspace"].get("discovery", {"max_depth": 3, "require_acceptance": True})
    if not isinstance(discovery, dict):
        raise ValueError("workspace.discovery must be an object")
    _nonnegative_int(discovery.get("max_depth", 3), "workspace.discovery.max_depth")
    if not isinstance(discovery.get("require_acceptance", True), bool):
        raise ValueError("workspace.discovery.require_acceptance must be boolean")
    orchestration = data["execution"].get("orchestration_budget")
    if not isinstance(orchestration, dict):
        raise ValueError("missing required section: execution.orchestration_budget")
    _positive_int(orchestration.get("max_agent_slots"), "execution.orchestration_budget.max_agent_slots")
    _nonnegative_int(orchestration.get("max_crg_calls"), "execution.orchestration_budget.max_crg_calls")
    _positive_int(orchestration.get("max_graph_depth"), "execution.orchestration_budget.max_graph_depth")
    _positive_int(orchestration.get("review_passes"), "execution.orchestration_budget.review_passes")
    _positive_int(orchestration.get("verification_passes"), "execution.orchestration_budget.verification_passes")
    _positive_int(data["handoff"].get("max_lines"), "handoff.max_lines")
    _positive_int(data["memory"].get("max_results"), "memory.max_results")


def parse_typed_config(data: dict[str, Any]):
    from .typed_config import ControlPlaneConfig

    migrated = migrate_config(data)
    validate_config(migrated)
    return ControlPlaneConfig.from_dict(migrated)


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / DEFAULT_RELATIVE).exists():
            return candidate
        if (candidate / "AGENTS.md").exists() and (candidate / "ai-workspace").exists():
            return candidate
    return current


def load_typed_config(root: Path):
    path = root / DEFAULT_RELATIVE
    if not path.exists():
        raise FileNotFoundError(f"control-plane config missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_typed_config(data)


def load_config(root: Path) -> dict[str, Any]:
    return load_typed_config(root).to_dict()


def estimate_tokens(text: str, estimator: TokenEstimator | None = None) -> int:
    return (estimator or _DEFAULT_TOKEN_ESTIMATOR).estimate(text)
