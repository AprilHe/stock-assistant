"""Loads machine-readable and human-readable strategy definitions."""

from __future__ import annotations

from pathlib import Path

import yaml

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"
STRATEGY_INDEX = STRATEGIES_DIR / "index.yaml"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"Strategy file not found: {path.name}")
    with path.open("r", encoding="utf-8") as f:
        parsed = yaml.safe_load(f) or {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid YAML object in {path.name}")
    return parsed


def list_strategies() -> list[dict]:
    index = _load_yaml(STRATEGY_INDEX)
    raw_items = index.get("strategies", [])
    if not isinstance(raw_items, list):
        raise ValueError("strategies/index.yaml must contain a top-level 'strategies' array.")
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        items.append(
            {
                "id": str(raw.get("id", "")).strip(),
                "name": str(raw.get("name", "")).strip(),
                "summary": str(raw.get("summary", "")).strip(),
                "tags": [str(t).strip() for t in raw.get("tags", []) if str(t).strip()],
                "asset_types": [str(a).strip() for a in raw.get("asset_types", []) if str(a).strip()],
                "capabilities": {
                    "analysis": bool((raw.get("capabilities") or {}).get("analysis")),
                    "screen": bool((raw.get("capabilities") or {}).get("screen")),
                    "backtest": bool((raw.get("capabilities") or {}).get("backtest")),
                },
                "python_impl": str(raw.get("python_impl", "")).strip(),
                "yaml_file": str(raw.get("yaml_file", "")).strip(),
                "md_file": str(raw.get("md_file", "")).strip(),
            }
        )
    return [x for x in items if x["id"] and x["name"] and x["yaml_file"] and x["md_file"]]


def _capability_enabled(item: dict, capability: str) -> bool:
    caps = item.get("capabilities", {})
    return bool(caps.get(capability, False))


def list_strategies_by_capability(capability: str) -> list[dict]:
    normalized = capability.lower().strip()
    if normalized not in {"analysis", "screen", "backtest"}:
        raise ValueError("capability must be one of: analysis | screen | backtest")
    return [item for item in list_strategies() if _capability_enabled(item, normalized)]


def get_strategy(strategy_id: str, capability: str = "") -> dict:
    target = strategy_id.lower().strip()
    if not target:
        raise ValueError("strategy_id is required.")
    normalized_capability = capability.lower().strip() if capability else ""
    if normalized_capability and normalized_capability not in {"analysis", "screen", "backtest"}:
        raise ValueError("capability must be one of: analysis | screen | backtest")

    for item in list_strategies():
        if item["id"] != target:
            continue
        if normalized_capability and not _capability_enabled(item, normalized_capability):
            raise ValueError(f"Strategy '{target}' does not support capability '{normalized_capability}'.")
        yaml_path = STRATEGIES_DIR / item["yaml_file"]
        md_path = STRATEGIES_DIR / item["md_file"]
        config = _load_yaml(yaml_path)
        if not md_path.exists():
            raise ValueError(f"Strategy documentation not found: {md_path.name}")
        documentation_md = md_path.read_text(encoding="utf-8")
        return {
            "id": item["id"],
            "name": item["name"],
            "summary": item["summary"],
            "tags": item["tags"],
            "asset_types": item["asset_types"],
            "capabilities": item["capabilities"],
            "python_impl": item["python_impl"],
            "config": config,
            "documentation_md": documentation_md,
        }

    raise ValueError(f"Unknown strategy: {strategy_id}")


def build_prompt_context(strategy_id: str) -> str:
    strategy = get_strategy(strategy_id, capability="analysis")
    cfg = strategy["config"]
    entry = cfg.get("entry_signals", [])
    exit_rules = cfg.get("exit_signals", [])
    risk = cfg.get("risk_controls", [])
    prompt_hints = cfg.get("prompt_hints", [])

    lines = [
        f"STRATEGY CONTEXT: {strategy['name']} ({strategy['id']})",
        f"Summary: {strategy['summary']}",
    ]
    if entry:
        lines.append(f"Entry signals: {', '.join(str(x) for x in entry)}")
    if exit_rules:
        lines.append(f"Exit signals: {', '.join(str(x) for x in exit_rules)}")
    if risk:
        lines.append(f"Risk controls: {', '.join(str(x) for x in risk)}")
    if prompt_hints:
        lines.append(f"Interpretation hints: {', '.join(str(x) for x in prompt_hints)}")
    return "\n".join(lines)
