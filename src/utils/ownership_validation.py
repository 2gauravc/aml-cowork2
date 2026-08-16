"""Deterministic integrity checks for a resolved ownership graph."""

from __future__ import annotations

from typing import Any


def validate_ownership_resolution(root: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable validation result without modifying extracted facts."""
    issues: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    seen: set[int] = set()
    stack: set[int] = set()

    def walk(node: dict[str, Any], path: list[str], effective: float) -> None:
        marker = id(node)
        name = str(node.get("name") or "Unidentified entity")
        if marker in stack:
            issues.append({"code": "ownership_cycle", "entity": name, "path": path + [name]})
            return
        if marker in seen:
            return
        seen.add(marker)
        stack.add(marker)
        children = [item for item in node.get("shareholders") or [] if isinstance(item, dict)]
        if children:
            percentages = []
            for child in children:
                value = (child.get("ownership") or {}).get("shares")
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    issues.append({"code": "missing_ownership_percentage", "entity": child.get("name") or name})
                    continue
                if value < 0 or value > 100:
                    issues.append({"code": "invalid_ownership_percentage", "entity": child.get("name") or name, "value": value})
                    continue
                percentages.append(value)
                walk(child, path + [name], effective * value / 100)
            if percentages and abs(sum(percentages) - 100) > 0.01:
                issues.append({"code": "direct_ownership_not_100", "entity": name, "total": round(sum(percentages), 2)})
        else:
            terminals.append({"entity": name, "effective_ownership_percent": round(effective, 2), "terminal_type": _terminal_type(node)})
        stack.remove(marker)

    if isinstance(root, dict) and root:
        walk(root, [], 100.0)
    else:
        issues.append({"code": "ownership_graph_missing", "entity": "Customer"})
    return {"outcome": "passed" if not issues else "requires_review", "issues": issues, "terminals": terminals}


def _terminal_type(node: dict[str, Any]) -> str:
    if node.get("nationality_id") is not None:
        return "individual"
    return "unresolved_entity"
