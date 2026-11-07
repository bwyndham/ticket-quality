"""The Ticket model and a forgiving Markdown parser.

One parser serves every source: tickets Claude writes, tickets people write in
Linear (Markdown) and Jira (ADF, converted to Markdown by `trackers.adf`), and
files. It never raises on odd input: missing parts come back empty, and the
rules decide what that means.

The agent context is found in this order:
  1. `<details>` whose `<summary>` mentions "agent"          -> style "collapsed"
  2. a Linear toggle: `+++ Agent context` ... `+++`           -> style "collapsed"
  3. a heading (any level) such as "Agent context", "Context for agents",
     "AI context" or "Implementation context": from there to the end -> style "heading"
Everything else is the human section.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

TicketType = Literal["story", "bug", "task"]
AcFormat = Literal["checklist", "gherkin", "prose", "none"]
AgentStyle = Literal["collapsed", "heading", "none"]


class Ticket(BaseModel):
    title: str = ""
    type: TicketType = "story"
    why: str = ""  # "## Why" or "## Impact": the problem or outcome behind the work
    summary: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    ac_format: AcFormat = "none"
    ac_raw: str = ""
    out_of_scope: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected: str = ""
    actual: str = ""
    other_sections: dict[str, str] = Field(default_factory=dict)
    human_markdown: str = ""  # what a reader sees without expanding the agent context
    agent_context: str | None = None
    agent_context_style: AgentStyle = "none"
    agent_context_last: bool = True  # nothing substantive follows the agent context
    markdown: str = ""  # the full ticket as given
    source: dict[str, Any] = Field(default_factory=dict)  # tracker, id, url

    def judge_view(self) -> dict[str, Any]:
        """The ticket as the judge (and the eval suite's checks) see it."""
        return self.model_dump(exclude={"ac_raw", "source", "other_sections"})


# --- section names -----------------------------------------------------------

_ALIASES: dict[str, tuple[str, ...]] = {
    "why": ("why", "impact", "why this matters", "why it matters", "problem", "motivation", "goal",
            "business impact", "user impact", "customer impact", "reason"),
    "summary": ("summary", "description", "overview", "context", "what", "user story", "background",
                "what and why", "tl;dr", "tldr"),
    "acceptance_criteria": ("acceptance criteria", "acceptance criterion", "ac", "a/c",
                            "definition of done", "done when", "success criteria",
                            "requirements", "criteria"),
    "out_of_scope": ("out of scope", "not in scope", "non-goals", "non goals", "out-of-scope",
                     "scope exclusions", "not included"),
    "open_questions": ("open questions", "questions", "unknowns", "open items"),
    "assumptions": ("assumptions", "assumed"),
    "steps_to_reproduce": ("steps to reproduce", "repro steps", "reproduction steps", "steps",
                           "how to reproduce", "to reproduce", "reproduce"),
    "expected": ("expected", "expected behaviour", "expected behavior", "expected result"),
    "actual": ("actual", "actual behaviour", "actual behavior", "actual result",
               "what happens", "current behaviour", "current behavior"),
}
_AGENT_HEADING = re.compile(
    r"(?i)\b(agent[s']*\s+context|context\s+for\s+(?:the\s+)?(?:agents?|ai|claude|llms?)|"
    r"ai\s+context|llm\s+context|implementation\s+context|for\s+(?:the\s+)?agents?)\b")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BOLD_HEADING = re.compile(r"^\*\*([^*]{2,60}?):?\*\*:?\s*$")  # **Acceptance criteria** on its own line
_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d{1,3}[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
_GHERKIN = re.compile(r"(?m)^\s*(?:Feature|Scenario(?: Outline| Template)?|Example|Given|When|Then)\b[:\s]")
_EMPTY_ITEM = re.compile(r"(?i)^(?:none|n/?a|nothing|-|—|tbd later)\.?$")


def _canonical(name: str) -> str | None:
    key = re.sub(r"[*_`:]+", "", name).strip().lower()
    key = re.sub(r"\s*\(.*\)$", "", key)  # "Open questions (optional)"
    for canon, aliases in _ALIASES.items():
        if key in aliases:
            return canon
    if key.startswith("expected") and "actual" in key:
        return "expected_vs_actual"
    return None


# --- agent context ---------------------------------------------------------------

_DETAILS = re.compile(
    r"<details[^>]*>\s*<summary[^>]*>(?P<summary>.*?)</summary>(?P<body>.*?)</details>",
    re.DOTALL | re.IGNORECASE)
_TOGGLE = re.compile(r"(?m)^\+\+\+[ \t]*(?P<summary>.+?)[ \t]*\n(?P<body>.*?)^\+\+\+[ \t]*$",
                     re.DOTALL)


def _split_agent_context(text: str) -> tuple[str, str | None, AgentStyle, bool]:
    """(human text, agent context, style, agent context is last)."""
    for pattern in (_DETAILS, _TOGGLE):
        for m in pattern.finditer(text):
            if re.search(r"(?i)\bagents?\b|\bai\b|\bclaude\b|\bllm", m.group("summary")):
                after = text[m.end():]
                human = (text[: m.start()] + "\n" + after).strip()
                return human, m.group("body").strip(), "collapsed", not _substantive(after)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        h = _HEADING.match(line.strip()) or _BOLD_HEADING.match(line.strip())
        title = h.group(h.lastindex) if h else ""
        if h and _AGENT_HEADING.search(title):
            human = "\n".join(lines[:i]).rstrip()
            human = re.sub(r"\n\s*(?:---|\*\*\*|___)\s*$", "", human).strip()  # trailing divider
            return human, "\n".join(lines[i + 1:]).strip(), "heading", True
    return text.strip(), None, "none", True


def _substantive(text: str) -> bool:
    return bool(re.sub(r"(?:---|\*\*\*|___|<br\s*/?>|\s)+", "", text))


# --- sections -----------------------------------------------------------------------

def _sections(text: str) -> tuple[str | None, str, list[tuple[str, str]]]:
    """(H1 title or None, preamble before the first heading, [(heading, body)])."""
    title = None
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        heading = None
        if not in_fence:
            m = _HEADING.match(stripped)
            if m:
                if len(m.group(1)) == 1 and title is None and not sections and not any(
                        p.strip() for p in preamble):
                    title = m.group(2).strip()
                    continue
                heading = m.group(2).strip()
            else:
                b = _BOLD_HEADING.match(stripped)
                if b and _canonical(b.group(1)):
                    heading = b.group(1).strip()
        if heading is not None:
            sections.append((heading, []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return title, "\n".join(preamble).strip(), [(h, "\n".join(b).strip()) for h, b in sections]


def list_items(body: str) -> list[str]:
    """Bullet or numbered items (checkboxes stripped, continuation lines joined).
    A body with no list markers gives one item per non-empty line."""
    items: list[str] = []
    saw_marker = False
    for line in body.split("\n"):
        if not line.strip() or line.strip().startswith("```"):
            continue
        m = _LIST_ITEM.match(line)
        if m:
            saw_marker = True
            items.append(m.group(1).strip())
        elif saw_marker and items and (line.startswith(" ") or line.startswith("\t")):
            items[-1] += " " + line.strip()
        elif not saw_marker:
            items.append(line.strip())
        else:
            items.append(line.strip())
    return [i for i in (s.strip() for s in items) if i and not _EMPTY_ITEM.match(i)]


def _strip_fences(body: str) -> str:
    return re.sub(r"(?m)^\s*(?:```|~~~)[\w-]*\s*$", "", body).strip()


def gherkin_scenarios(text: str) -> list[str]:
    """Each Scenario block as one string (name plus steps)."""
    blocks: list[list[str]] = []
    for line in text.split("\n"):
        s = line.strip()
        if re.match(r"(?:Scenario(?: Outline| Template)?|Example)\s*:", s):
            blocks.append([s])
        elif blocks and s and not s.startswith("Feature:"):
            blocks[-1].append(s)
    return [" / ".join(b) for b in blocks]


def _parse_ac(body: str) -> tuple[list[str], AcFormat]:
    if not body.strip():
        return [], "none"
    if _GHERKIN.search(body):
        scenarios = gherkin_scenarios(_strip_fences(body))
        return (scenarios or [_strip_fences(body)]), "gherkin"
    items = list_items(body)
    has_markers = any(_LIST_ITEM.match(line) for line in body.split("\n"))
    return items, ("checklist" if has_markers else "prose")


_TYPE_LINE = re.compile(r"(?im)^\s*(?:\*\*)?(?:type|issue type|ticket type)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(\w+)\**\s*$")


def normalise_type(value: str | None) -> TicketType | None:
    if not value:
        return None
    v = value.strip().lower()
    if v in ("bug", "defect", "incident", "problem"):
        return "bug"
    if v in ("story", "user story", "feature", "improvement", "enhancement", "new feature", "epic"):
        return "story"
    if v in ("task", "chore", "sub-task", "subtask", "spike", "tech debt", "technical task"):
        return "task"
    return None


def parse_ticket(markdown: str, *, title: str | None = None, ticket_type: str | None = None,
                 source: dict[str, Any] | None = None) -> Ticket:
    text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    human, agent, style, agent_last = _split_agent_context(text)

    type_match = _TYPE_LINE.search(human)
    found_type = normalise_type(type_match.group(1)) if type_match else None
    if type_match:
        human_body = human[: type_match.start()] + human[type_match.end():]
    else:
        human_body = human
    h1, preamble, sections = _sections(human_body)

    t = Ticket(markdown=text, source=dict(source or {}))
    t.title = (title or h1 or "").strip()
    if not t.title:
        m = re.search(r"(?im)^\s*(?:\*\*)?title(?:\*\*)?\s*:\s*(.+)$", preamble)
        if m:
            t.title = m.group(1).strip().strip("*")
            preamble = (preamble[: m.start()] + preamble[m.end():]).strip()

    summary_parts: list[str] = []
    for heading, body in sections:
        canon = _canonical(heading)
        if canon == "summary":
            summary_parts.append(body)
        elif canon == "why":
            t.why = (t.why + "\n" + body).strip()
        elif canon == "acceptance_criteria":
            t.ac_raw = (t.ac_raw + "\n" + body).strip()
        elif canon in ("out_of_scope", "open_questions", "assumptions", "steps_to_reproduce"):
            getattr(t, canon).extend(list_items(body))
        elif canon in ("expected", "actual"):
            setattr(t, canon, (getattr(t, canon) + "\n" + body).strip())
        elif canon == "expected_vs_actual":
            exp = re.search(r"(?is)expected\W*(.*?)(?:\n\s*\W*actual|$)", body)
            act = re.search(r"(?is)actual\W*(.*)$", body)
            t.expected = (exp.group(1).strip() if exp else body)
            t.actual = act.group(1).strip() if act else ""
        else:
            t.other_sections[heading] = body
    if preamble:
        summary_parts.insert(0, preamble)
    t.summary = "\n\n".join(p for p in summary_parts if p).strip()
    t.acceptance_criteria, t.ac_format = _parse_ac(t.ac_raw)

    # Assumptions and questions written inside the agent context count too.
    if agent:
        _, _, agent_sections = _sections(agent)
        for heading, body in agent_sections:
            canon = _canonical(heading)
            if canon in ("assumptions", "open_questions"):
                getattr(t, canon).extend(list_items(body))

    t.type = normalise_type(ticket_type) or found_type or (
        "bug" if (t.steps_to_reproduce or t.actual) else "story")
    t.human_markdown = human.strip()
    t.agent_context = agent
    t.agent_context_style = style
    t.agent_context_last = agent_last
    return t


__all__ = ["Ticket", "gherkin_scenarios", "list_items", "normalise_type", "parse_ticket"]
