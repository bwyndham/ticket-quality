"""Load the standard: rules (ticket-standard.yaml), rubric (rubric.yaml),
writer guide (writer-guide.md) and judge prompts (judge/*.jinja).

The standard folder is, in order: `--standard DIR` / the `directory` argument,
$TICKET_STANDARD_DIR, or this repo's `standard/` (found when the package is
installed editable or run from a checkout).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Severity = Literal["error", "warn", "info"]
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Rule:
    id: str
    group: str
    severity: Severity
    what: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RubricItem:
    id: str
    question: str
    severity: Severity
    applies: Literal["always", "bug", "with_ask"]


@dataclass(frozen=True)
class Standard:
    dir: Path
    rules: list[Rule]
    rubric: list[RubricItem]

    def rule(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    @property
    def rubric_path(self) -> Path:
        return self.dir / "rubric.yaml"

    @property
    def writer_guide_path(self) -> Path:
        return self.dir / "writer-guide.md"

    @property
    def judge_system_path(self) -> Path:
        return self.dir / "judge" / "system.jinja"

    @property
    def judge_user_path(self) -> Path:
        return self.dir / "judge" / "user.jinja"


def standard_dir(directory: str | Path | None = None) -> Path:
    candidates = [directory, os.environ.get("TICKET_STANDARD_DIR"), REPO_ROOT / "standard"]
    for c in candidates:
        if c and (Path(c) / "ticket-standard.yaml").is_file():
            return Path(c).resolve()
    raise FileNotFoundError(
        "ticket standard not found: pass --standard DIR, set TICKET_STANDARD_DIR, or install "
        "ticket-quality editable from its repo (uv tool install --editable .)")


def load_standard(directory: str | Path | None = None) -> Standard:
    d = standard_dir(directory)
    raw = yaml.safe_load((d / "ticket-standard.yaml").read_text(encoding="utf-8")) or {}
    rules = []
    for r in raw.get("rules") or []:
        sev = r.get("severity", "warn")
        if sev not in ("error", "warn", "info"):
            raise ValueError(f"rule {r.get('id')!r}: severity must be error, warn or info")
        rules.append(Rule(id=r["id"], group=r.get("group", "precise"), severity=sev,
                          what=r.get("what", ""), params=r.get("params") or {}))
    rraw = yaml.safe_load((d / "rubric.yaml").read_text(encoding="utf-8")) or {}
    items = rraw.get("items", rraw) if isinstance(rraw, dict) else rraw
    rubric = [RubricItem(id=i["id"], question=" ".join(str(i["question"]).split()),
                         severity=i.get("severity", "error"), applies=i.get("applies", "always"))
              for i in items]
    return Standard(dir=d, rules=rules, rubric=rubric)


__all__ = ["REPO_ROOT", "Rule", "RubricItem", "Severity", "Standard", "load_standard", "standard_dir"]
