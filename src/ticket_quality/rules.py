"""The deterministic half of the standard: one function per rule id.

Each rule returns findings; a rule with nothing to say returns []. The rule's
severity and params come from ticket-standard.yaml, so tuning a threshold
never needs a code change. A rule id in the YAML with no function here is an
error (caught by the tests), and so is the reverse.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ticket_quality.standard import Rule, Severity, Standard
from ticket_quality.ticket import Ticket, gherkin_scenarios


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    fix: str = ""
    source: str = "rule"  # rule | judge

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "severity": self.severity, "message": self.message,
                "fix": self.fix, "source": self.source}


RuleFn = Callable[[Ticket, dict[str, Any]], list[tuple[str, str]]]  # -> [(message, fix)]
RULES: dict[str, RuleFn] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    def deco(fn: RuleFn) -> RuleFn:
        RULES[rule_id] = fn
        return fn
    return deco


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][\w'’./%-]*", text or ""))


def _short(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def human_words(t: Ticket) -> int:
    """Words a reader meets in the human section, title and type line excluded."""
    body = re.sub(r"(?m)^\s*#\s+.*$", "", t.human_markdown, count=1)
    body = re.sub(r"(?im)^\s*(?:\*\*)?(?:type|issue type)(?:\*\*)?\s*:.*$", "", body)
    body = re.sub(r"(?m)^\s*#{2,6}\s+.*$", "", body)  # section headings aren't reading load
    body = re.sub(r"\[[ xX]\]", "", body)
    return words(body)


# --- structure ---------------------------------------------------------------------

_FIELD_LABEL = {"title": "a title", "why": "a Why (or Impact) section", "summary": "a Summary",
                "acceptance_criteria": "Acceptance criteria",
                "steps_to_reproduce": "Steps to reproduce", "expected": "Expected behaviour",
                "actual": "Actual behaviour"}


@rule("required_sections")
def _required(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for f in p.get(t.type, []):
        value = getattr(t, f, None)
        if not value or (isinstance(value, str) and not value.strip()):
            label = _FIELD_LABEL.get(f, f)
            if f == "title":
                fix = "Give the ticket a title that names the change."
            elif f == "why":
                fix = ("Add `## Impact`: who is affected, how often, how badly." if t.type == "bug" else
                       "Add `## Why`: the problem or outcome this serves. If nobody has said, write "
                       "'Not stated' and ask under Open questions.")
            else:
                fix = f"Add a `## {label.removeprefix('a ').removeprefix('A ')}` section."
            out.append((f"{t.type.capitalize()} is missing {label}.", fix))
    return out


@rule("placeholders")
def _placeholders(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    text = t.title + "\n" + re.sub(r"(?is)</?(?:details|summary|br)[^>]*>", "", t.human_markdown)
    hits = []
    for pat in p.get("patterns", []):
        for m in re.finditer(pat, text):
            hits.append(m.group(0))
    if not hits:
        return []
    uniq = sorted(set(hits))
    return [(f"Unfinished placeholder(s) in the human section: {', '.join(uniq[:5])}.",
             "Fill them in, or turn each unknown into an open question.")]


@rule("gherkin_valid")
def _gherkin(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if t.ac_format != "gherkin":
        return []
    from gherkin import Parser
    from gherkin.errors import CompositeParserException, ParserError

    body = re.sub(r"(?m)^\s*(?:```|~~~)[\w-]*\s*$", "", t.ac_raw).strip()
    if not re.search(r"(?m)^\s*Feature:", body):
        body = "Feature: Acceptance criteria\n" + body
    body = "\n".join(line.strip() for line in body.split("\n"))
    try:
        Parser().parse(body)
    except (ParserError, CompositeParserException) as exc:
        first = str(exc).split("\n")[0]
        return [(f"Gherkin doesn't parse: {_short(first, 120)}",
                 "Use Scenario: blocks of Given / When / Then steps, one step per line.")]
    out = []
    for sc in gherkin_scenarios(body):
        if not re.search(r"(?:^| / )Then\b", sc):
            out.append((f"Scenario has no Then step: {_short(sc.split(' / ')[0])}",
                        "Add a Then step stating the observable outcome."))
    return out


# --- skimmable -------------------------------------------------------------------

@rule("human_section_budget")
def _budget(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    n = human_words(t)
    warn_at, max_at = p.get("warn_words", 200), p.get("max_words", 220)
    if n > max_at:
        return [(f"Human section is {n} words (limit {max_at}); readers will skim past it.",
                 "Move background, rationale and technical detail into the collapsed Agent context.")]
    if n > warn_at:
        return [(f"WARN_ONLY Human section is {n} words (aim for {warn_at} or fewer).",
                 "Trim the summary or move detail into the Agent context.")]
    return []


def _sentences(text: str) -> int:
    text = re.sub(r"\b(?:e\.g|i\.e|etc|vs)\.", "", text)
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


@rule("summary_length")
def _summary(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if not t.summary:
        return []
    n, s = words(t.summary), _sentences(t.summary)
    if n < p.get("min_words", 5):
        return [(f"Summary is only {n} words: it doesn't say what changes and for whom.",
                 "Say in a sentence what will be different and who it's for.")]
    if n > p.get("max_words", 70) or s > p.get("max_sentences", 4):
        return [(f"Summary is {n} words / {s} sentences; aim for 1 to {p.get('max_sentences', 4)} short sentences.",
                 "Keep what, who and why; move the rest into the Agent context.")]
    return []


@rule("ac_item_length")
def _ac_length(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for i, item in enumerate(t.acceptance_criteria, 1):
        if t.ac_format == "gherkin":
            steps = len(item.split(" / ")) - 1
            if steps > p.get("max_scenario_steps", 8):
                out.append((f"Scenario {i} has {steps} steps: {_short(item.split(' / ')[0])}",
                            "Split it into smaller scenarios."))
        elif words(item) > p.get("max_words", 30):
            out.append((f"AC {i} is {words(item)} words: \"{_short(item)}\"",
                        "Make it one checkable statement; split compound criteria."))
    return out


@rule("agent_detail_in_human_section")
def _agent_detail(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    human = t.human_markdown
    out = []
    fences = re.findall(r"(?ms)^\s*(?:```|~~~)([\w-]*)\s*$(.*?)^\s*(?:```|~~~)\s*$", human)
    code = [f for f in fences if f[0].lower() not in ("gherkin", "feature", "cucumber")]
    if code:
        out.append((f"{len(code)} code block(s) in the human section.",
                    "Move code, payloads and logs into the Agent context."))
    no_fences = re.sub(r"(?ms)^\s*(?:```|~~~).*?^\s*(?:```|~~~)\s*$", "", human)
    paths = sorted(set(re.findall(p.get("path_pattern", r"$^"), no_fences)))
    if paths:
        out.append((f"File paths in the human section: {', '.join(paths[:3])}"
                    + (" …" if len(paths) > 3 else ""),
                    "Move file and code pointers into the Agent context's implementation notes."))
    if re.search(p.get("trace_pattern", r"$^"), human):
        out.append(("Stack trace in the human section.",
                    "Keep a one-line error message under Actual; put the trace in the Agent context."))
    inline = re.findall(r"`[^`\n]+`", no_fences)
    if len(inline) > p.get("max_inline_code", 3):
        out.append((f"{len(inline)} inline code spans in the human section.",
                    "Describe behaviour in plain words; keep identifiers in the Agent context."))
    return out


@rule("agent_context_placement")
def _placement(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if t.agent_context is not None and not t.agent_context_last:
        return [("Agent context isn't the last section, so readers hit content after it.",
                 "Move the Agent context to the very end of the ticket.")]
    return []


@rule("agent_context_collapsed")
def _collapsed(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if t.agent_context_style == "heading":
        return [("Agent context is a plain heading, not collapsed.",
                 "Wrap it in <details>, a Linear `+++ Agent context` toggle, or a Jira expand block.")]
    return []


# --- precise ------------------------------------------------------------------------

@rule("title_length")
def _title_length(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if not t.title:
        return []  # required_sections reports it
    out = []
    if len(t.title) > p.get("max_chars", 80):
        out.append((f"Title is {len(t.title)} characters (max {p.get('max_chars', 80)}).",
                    "Cut it to the change itself; details go in the summary."))
    if words(t.title) < p.get("min_words", 3):
        out.append((f"Title \"{t.title}\" is too short to say what changes.",
                    "Name the change: what will be different when this ships."))
    return out


@rule("title_vague")
def _title_vague(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if not t.title:
        return []
    title = t.title.lower()
    vague = [w for w in p.get("vague_words", []) if re.search(rf"\b{re.escape(w)}\b", title)]
    opener = next((o for o in p.get("vague_openers", []) if re.match(rf"{re.escape(o)}\b", title)), None)
    short = opener and words(t.title) - len(opener.split()) < p.get("short_title_words", 4)
    if vague or short:
        why = f"vague word(s): {', '.join(vague)}" if vague else f"\"{opener}\" + a topic"
        return [(f"Title \"{t.title}\" reads like a topic ({why}).",
                 "Say what will be different, e.g. \"Send overdue reminders 3 days after due date\".")]
    return []


@rule("ac_count")
def _ac_count(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    n = len(t.acceptance_criteria)
    if t.acceptance_criteria and n > p.get("max", 10):
        return [(f"{n} acceptance criteria: this is probably more than one ticket.",
                 "Split it into separate tickets, each one deliverable.")]
    return []


def _term_regex(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?i)(?<![\w-]){term}(?![\w-])")


@rule("ac_vague_language")
def _ac_vague(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    always = [(term, _term_regex(term)) for term in p.get("terms", [])]
    numeric = [(term, _term_regex(term)) for term in p.get("numeric_terms", [])]
    for i, item in enumerate(t.acceptance_criteria, 1):
        hits = [m.group(0) for _, rx in always if (m := rx.search(item))]
        if not re.search(r"\d", item):
            hits += [m.group(0) for _, rx in numeric if (m := rx.search(item))]
        if hits:
            label = "Scenario" if t.ac_format == "gherkin" else "AC"
            out.append((f"{label} {i} uses untestable wording ({', '.join(dict.fromkeys(h.lower() for h in hits))}): "
                        f"\"{_short(item)}\"",
                        "State the observable result, with a number where it's about speed, size or amount."))
    return out


@rule("open_questions_unresolved")
def _open_questions(t: Ticket, p: dict[str, Any]) -> list[tuple[str, str]]:
    if t.open_questions:
        return [(f"{len(t.open_questions)} open question(s): not ready for a sprint until answered.",
                 "Get answers, then fold them into the summary or criteria.")]
    return []


# --- run ---------------------------------------------------------------------------------

def run_rules(ticket: Ticket, standard: Standard, *, groups: set[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for r in standard.rules:
        if groups is not None and r.group not in groups:
            continue
        fn = RULES.get(r.id)
        if fn is None:
            raise KeyError(f"standard has rule {r.id!r} but ticket_quality.rules has no function for it")
        for message, fix in fn(ticket, r.params):
            severity: Severity = r.severity
            if message.startswith("WARN_ONLY "):  # a softer tier of an error rule
                message, severity = message.removeprefix("WARN_ONLY "), "warn"
            findings.append(Finding(rule=r.id, severity=severity, message=message, fix=fix))
    return findings


def rule_group(rules: list[Rule], rule_id: str) -> str | None:
    return next((r.group for r in rules if r.id == rule_id), None)


__all__ = ["Finding", "RULES", "human_words", "run_rules", "words"]
