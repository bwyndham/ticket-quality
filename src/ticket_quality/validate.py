"""Validate one ticket: rules, then (optionally) the judge, then a verdict."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ticket_quality.rules import Finding, human_words, run_rules
from ticket_quality.standard import Standard
from ticket_quality.ticket import Ticket

Verdict = Literal["PASS", "WARN", "FAIL"]


@dataclass
class Report:
    ticket: Ticket
    findings: list[Finding]
    judged: bool
    judge_note: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    def verdict(self, strict: bool = False) -> Verdict:
        sev = {f.severity for f in self.findings}
        if "error" in sev or (strict and "warn" in sev):
            return "FAIL"
        return "WARN" if "warn" in sev else "PASS"

    def as_dict(self, strict: bool = False) -> dict[str, Any]:
        t = self.ticket
        return {
            "verdict": self.verdict(strict),
            "ticket": {"title": t.title, "type": t.type, **{k: v for k, v in t.source.items()}},
            "judged": self.judged,
            "judge_note": self.judge_note,
            "stats": self.stats,
            "findings": [f.as_dict() for f in self.findings],
        }


_ORDER = {"error": 0, "warn": 1, "info": 2}


def validate(ticket: Ticket, standard: Standard, *, judge_client: Any | None = None,
             ask: str | None = None, siblings: list[Ticket] | None = None) -> Report:
    """`siblings`: the other tickets written from the same request, so questions about
    the request as a whole are judged across the set."""
    findings = run_rules(ticket, standard)
    judged, note = False, ""
    if judge_client is not None:
        from ticket_quality.judge import judge_ticket

        try:
            findings += judge_ticket(ticket, standard, judge_client, ask=ask, siblings=siblings)
            judged = True
        except Exception as exc:  # noqa: BLE001 - rules still stand on their own
            note = f"judge skipped: {type(exc).__name__}: {exc}"
    findings.sort(key=lambda f: (_ORDER[f.severity], f.source != "rule"))
    stats = {
        "human_words": human_words(ticket),
        "acceptance_criteria": len(ticket.acceptance_criteria),
        "ac_format": ticket.ac_format,
        "agent_context": ticket.agent_context_style,
    }
    return Report(ticket=ticket, findings=findings, judged=judged, judge_note=note, stats=stats)


__all__ = ["Report", "Verdict", "validate"]
