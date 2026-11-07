"""llm-evals plug-ins for the ticket-writing suite.

- Schema `ticket_markdown`: the writer returns {"ticket_markdown": "..."}; the
  schema parses it with the same parser `ticket-lint` uses, so every check (and
  the judge) sees the same parsed ticket the CLI would.
- Checks `ticket_structure`, `ticket_skimmable`, `ticket_precise`: the standard's
  rules, one gated check per group, failing on error-severity findings.
- Check `covers_ask`: on cases rendered from known requirement atoms, every
  stated requirement shows up in an acceptance criterion (or, for bugs, the
  steps / expected / actual). The summary, assumptions, open questions, out of
  scope and agent context don't count as covering a requirement.

The judge half is llm-evals' built-in `checklist`, pointed at standard/rubric.yaml
and standard/judge/*.jinja, so its questions are the ones `ticket-lint` asks.
"""

from __future__ import annotations

import math
import re
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


_TOKEN = re.compile(r"[a-z0-9]+(?:[.%+-][a-z0-9%+]+)*%?\+?")


def _stem(word: str) -> str:
    """Crude, consistent stemming: 'rates'/'rate', 'named'/'name', 'syncs'/'sync' meet."""
    if not word.isalpha() or len(word) <= 3:
        return word
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def _words(text: str) -> list[str]:
    """Lowercase tokens, plus the parts of hyphenated words ("overdue-invoice" -> overdue, invoice).
    Number ranges like 0-30 stay whole."""
    out = []
    for tok in _TOKEN.findall(text.lower()):
        out.append(tok)
        if "-" in tok and not re.fullmatch(r"[\d.%+-]+", tok):
            out += [p for p in tok.split("-") if p]
    return out


def stems(text: str) -> list[str]:
    return [_stem(w) for w in _words(text)]


_FILLER = {"a", "an", "the", "of", "to", "for", "and", "level", "by", "in", "on"}


def keyword_in(keyword: str, places: list[str]) -> bool:
    """A keyword counts when every one of its words appears in ONE criterion, in any order
    and any form: same stem ("api keys" ~ "an API key"), or the criterion word starts with
    it (the atoms use prefixes like "approv" and "retr")."""
    kw_words = [w for w in _words(keyword) if w not in _FILLER] or _words(keyword)
    for place in places:
        words = _words(place)
        word_stems = {_stem(w) for w in words}
        if all(_stem(k) in word_stems or any(w.startswith(k) for w in words) for k in kw_words):
            return True
    return False


def _hinted(case: Case) -> set[str]:
    src = case.source or {}
    hinted = set(src.get("hinted_atom_ids") or [])
    hinted |= {a["id"] for a in src.get("atoms") or [] if a.get("mode") == "hinted"}
    return hinted


class CoversAsk(BaseCheck):
    name = "covers_ask"
    kind = "deterministic"

    def __init__(self, *, min_keyword_share: float, critical: bool) -> None:
        super().__init__(critical=critical)
        self.min_share = min_keyword_share

    def applies(self, case: Case) -> bool:
        return bool((case.source or {}).get("atoms"))

    def _score(self, case: Case, output: dict[str, Any], ctx: CheckContext) -> Score:
        # Only testable places count: a requirement pasted into the summary or the
        # agent context isn't covered until a criterion (or bug field) states it.
        places = [*(output.get("acceptance_criteria") or []), *(output.get("steps_to_reproduce") or []),
                  output.get("expected") or "", output.get("actual") or ""]
        hinted = _hinted(case)
        missing, subs = [], []
        for atom in case.source["atoms"]:
            kws = [k.lower() for k in atom.get("keywords") or []]
            need = math.ceil(self.min_share * len(kws)) if kws else 0
            found = [k for k in kws if keyword_in(k, [p for p in places if p])]
            covered = len(found) >= need
            required = atom["id"] not in hinted
            subs.append({"atom": atom["id"], "required": required, "covered": covered, "found": found})
            if required and not covered:
                missing.append(atom.get("text") or atom["id"])
        n_req = sum(1 for s in subs if s["required"])
        value = (n_req - len(missing)) / n_req if n_req else 1.0
        if missing:
            return self.fail(f"{len(missing)} stated requirement(s) not in the acceptance criteria: "
                             + "; ".join(missing[:3]), value=value, sub_scores=subs)
        return Score(check=self.name, kind=self.kind, passed=True, value=value,
                     reason=f"all {n_req} stated requirement(s) covered", sub_scores=subs)


@register_check("covers_ask")
def covers_ask(*, min_keyword_share: float = 0.6, critical: bool = False) -> CoversAsk:
    return CoversAsk(min_keyword_share=min_keyword_share, critical=critical)


__all__ = ["CoversAsk", "RuleGroupCheck", "TicketOutput"]
