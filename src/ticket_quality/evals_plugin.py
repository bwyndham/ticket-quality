"""llm-evals plug-ins for the ticket-writing suite.

- Schema `ticket_markdown`: the writer returns {"ticket_markdown": "..."} holding one
  or more tickets, each starting with its own `# Title`. The schema splits and parses
  them with the same parser `ticket-lint` uses. The stored output is:
    tickets               one parsed ticket per item (see Ticket.judge_view)
    n_tickets
    markdown              the writer's full Markdown
    titles, acceptance_criteria, steps_to_reproduce, expected, actual,
    assumptions, open_questions
                          every ticket's items, concatenated, so built-in checks
                          (requirements_covered, gaps_flagged) work on the set
- Checks `ticket_structure`, `ticket_skimmable`, `ticket_precise`: the standard's
  rules, one gated check per group, run on every ticket; a case fails if any
  ticket has an error-severity finding.
- Check `tickets_split`: on cases rendered from known requirement sets, no ticket holds
  requirements from two separate requests, and there are at least as many tickets as
  requests. Splitting one request into several tickets is fine (a feature can ship
  in parts); merging two is not.

Requirement coverage is llm-evals' built-in `requirements_covered`, pointed at the
concatenated acceptance criteria (and bug fields) in suite.yaml. The judge half is
llm-evals' built-in `checklist`, pointed at standard/rubric.yaml and
standard/judge/*.jinja, so its questions are the ones `ticket-lint` asks.
"""

from __future__ import annotations

import math
from typing import Any

from llm_evals.api import BaseCheck, Case, CheckContext, Score, register_check, register_schema
from llm_evals.checks.keywords import keyword_in_any
from pydantic import BaseModel, ConfigDict

from ticket_quality.rules import run_rules
from ticket_quality.standard import load_standard
from ticket_quality.ticket import Ticket, parse_tickets

_STANDARD = None


def standard():
    global _STANDARD
    if _STANDARD is None:
        _STANDARD = load_standard()
    return _STANDARD


def output_of(markdown: str) -> dict[str, Any]:
    tickets = parse_tickets(markdown)
    out: dict[str, Any] = {"tickets": [t.judge_view() for t in tickets], "n_tickets": len(tickets),
                           "markdown": markdown, "titles": [t.title for t in tickets if t.title]}
    for key in ("acceptance_criteria", "steps_to_reproduce", "assumptions", "open_questions"):
        out[key] = [item for t in tickets for item in getattr(t, key)]
    for key in ("expected", "actual"):
        out[key] = [getattr(t, key) for t in tickets if getattr(t, key)]
    return out


@register_schema("ticket_markdown")
class TicketOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_markdown: str

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # noqa: D401 - what the runner stores as output
        return output_of(self.ticket_markdown)


def tickets_in(output: dict[str, Any]) -> list[Ticket]:
    """The parsed tickets of a stored output (re-parsed from its Markdown, so parser and
    rule changes apply to stored runs on rescore)."""
    return parse_tickets(output.get("markdown", ""))


class RuleGroupCheck(BaseCheck):
    kind = "deterministic"

    def __init__(self, *, name: str, group: str, critical: bool) -> None:
        self.name = name
        self.group = group
        super().__init__(critical=critical)

    def _score(self, case: Case, output: dict[str, Any], ctx: CheckContext) -> Score:
        tickets = tickets_in(output)
        subs: list[dict[str, Any]] = []
        errors: list[str] = []
        n_warn = 0
        for i, ticket in enumerate(tickets, 1):
            label = f"ticket {i}" if len(tickets) > 1 else "ticket"
            for f in run_rules(ticket, standard(), groups={self.group}):
                subs.append({"ticket": i, **f.as_dict()})
                if f.severity == "error":
                    errors.append(f"{label}: {f.rule}: {f.message}")
                elif f.severity == "warn":
                    n_warn += 1
        if errors:
            return self.fail(f"{len(errors)} error(s): " + "; ".join(errors[:3]), sub_scores=subs, value=0.0)
        reason = "ok" if not n_warn else f"ok, {n_warn} warning(s)"
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


def request_sets(case: Case) -> dict[str, list[dict[str, Any]]]:
    """Required (non-hinted) atoms grouped by the separate request they belong to."""
    source = case.source or {}
    hinted = set(source.get("hinted_atom_ids") or [])
    sets: dict[str, list[dict[str, Any]]] = {}
    for atom in source.get("atoms") or []:
        if atom.get("mode") == "hinted" or atom.get("id") in hinted or not atom.get("keywords"):
            continue
        sets.setdefault(str(atom.get("set_id") or "request"), []).append(atom)
    return sets


class TicketsSplit(BaseCheck):
    name = "tickets_split"
    kind = "deterministic"

    def __init__(self, *, min_keyword_share: float, critical: bool) -> None:
        super().__init__(critical=critical)
        self.min_share = min_keyword_share

    def applies(self, case: Case) -> bool:
        return bool(request_sets(case))

    def _covered(self, atom: dict[str, Any], places: list[str]) -> bool:
        kws = [str(k) for k in atom["keywords"]]
        need = max(1, math.ceil(self.min_share * len(kws) - 1e-9))
        return sum(keyword_in_any(k, places, "words") for k in kws) >= need

    def _score(self, case: Case, output: dict[str, Any], ctx: CheckContext) -> Score:
        sets = request_sets(case)
        tickets = tickets_in(output)
        places = [[*t.acceptance_criteria, *t.steps_to_reproduce, t.expected, t.actual] for t in tickets]
        subs: list[dict[str, Any]] = []
        holders: dict[int, list[str]] = {}  # ticket index -> requests it holds requirements of
        for set_id, atoms in sets.items():
            counts = [sum(self._covered(a, p) for a in atoms) for p in places]
            for i, n in enumerate(counts):
                if n:
                    holders.setdefault(i, []).append(set_id)
            subs.append({"request": set_id, "covered_per_ticket": counts, "required": len(atoms)})
        problems: list[str] = []
        if len(tickets) < len(sets):
            problems.append(f"{len(tickets)} ticket(s) for {len(sets)} separate request(s)")
        mixed = [i + 1 for i, reqs in sorted(holders.items()) if len(reqs) > 1]
        if mixed:
            problems.append(f"ticket(s) {', '.join(map(str, mixed))} hold requirements from separate requests")
        if problems:
            return self.fail("; ".join(problems), sub_scores=subs, value=0.0)
        return Score(check=self.name, kind=self.kind, passed=True, value=1.0,
                     reason=f"{len(sets)} request(s) in {len(tickets)} ticket(s), none merged", sub_scores=subs)


@register_check("tickets_split")
def tickets_split(*, min_keyword_share: float = 0.6, critical: bool = False) -> TicketsSplit:
    return TicketsSplit(min_keyword_share=min_keyword_share, critical=critical)


__all__ = ["RuleGroupCheck", "TicketOutput", "TicketsSplit", "output_of", "request_sets"]
