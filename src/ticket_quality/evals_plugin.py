"""llm-evals plug-ins for the ticket-writing suite.

- Schema `ticket_markdown`: the writer returns {"ticket_markdown": "..."}; the
  schema parses it with the same parser `ticket-lint` uses, so every check (and
  the judge) sees the same parsed ticket the CLI would.
- Checks `ticket_structure`, `ticket_skimmable`, `ticket_precise`: the standard's
  rules, one gated check per group, failing on error-severity findings.

Requirement coverage is llm-evals' built-in `requirements_covered`, pointed at
the acceptance criteria (and the bug fields) in suite.yaml.
The judge half is llm-evals' built-in `checklist`, pointed at standard/rubric.yaml
and standard/judge/*.jinja, so its questions are the ones `ticket-lint` asks.
"""

from __future__ import annotations

from typing import Any

from llm_evals.api import BaseCheck, Case, CheckContext, Score, register_check, register_schema
from pydantic import BaseModel, ConfigDict

from ticket_quality.rules import run_rules
from ticket_quality.standard import load_standard
from ticket_quality.ticket import parse_ticket

_STANDARD = None


def standard():
    global _STANDARD
    if _STANDARD is None:
        _STANDARD = load_standard()
    return _STANDARD


@register_schema("ticket_markdown")
class TicketOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_markdown: str

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # noqa: D401 - what the runner stores as output
        return parse_ticket(self.ticket_markdown).judge_view()


class RuleGroupCheck(BaseCheck):
    kind = "deterministic"

    def __init__(self, *, name: str, group: str, critical: bool) -> None:
        self.name = name
        self.group = group
        super().__init__(critical=critical)

    def _score(self, case: Case, output: dict[str, Any], ctx: CheckContext) -> Score:
        ticket = parse_ticket(output.get("markdown", ""), title=output.get("title") or None,
                              ticket_type=output.get("type"))
        findings = run_rules(ticket, standard(), groups={self.group})
        errors = [f for f in findings if f.severity == "error"]
        subs = [f.as_dict() for f in findings]
        if errors:
            return self.fail(f"{len(errors)} error(s): " + "; ".join(f"{f.rule}: {f.message}" for f in errors[:3]),
                             sub_scores=subs, value=0.0)
        warns = [f for f in findings if f.severity == "warn"]
        reason = "ok" if not warns else f"ok, {len(warns)} warning(s): " + ", ".join(f.rule for f in warns)
        return Score(check=self.name, kind=self.kind, passed=True, value=1.0, reason=reason, sub_scores=subs)


@register_check("ticket_structure")
def ticket_structure(*, critical: bool = False) -> RuleGroupCheck:
    return RuleGroupCheck(name="ticket_structure", group="structure", critical=critical)


@register_check("ticket_skimmable")
def ticket_skimmable(*, critical: bool = False) -> RuleGroupCheck:
    return RuleGroupCheck(name="ticket_skimmable", group="skimmable", critical=critical)


@register_check("ticket_precise")
def ticket_precise(*, critical: bool = False) -> RuleGroupCheck:
    return RuleGroupCheck(name="ticket_precise", group="precise", critical=critical)


__all__ = ["RuleGroupCheck", "TicketOutput"]
