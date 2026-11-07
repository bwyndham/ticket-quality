"""An offline stand-in for the ticket writer, for `--provider mock`.

It is not a model. It pulls request-like sentences out of the ask and lays
them out as a ticket, so the whole pipeline (cases, schema, checks, gate,
report) runs with no API key and no cost. It proves the wiring, not quality.

Its output depends on the system prompt the way a real model's would, so the
seeded variant really is caught:
- If the prompt asks for a collapsed agent context (mentions "Agent context"
  and "<details>"), background and assumptions go there. Otherwise the whole
  request is quoted as background in the human section, which blows the
  word budget.
- If the prompt bans untestable wording ("words a tester can't check"),
  criteria are the request sentences; otherwise some get "works correctly"
  tacked on.
- If the prompt says to flag gaps, a missing actor becomes an assumption.
"""

from __future__ import annotations

import json
import re
from typing import Any

_CUES = re.compile(r"(?i)\b(can we|could we|we need|need(?:s)? to|should|must|want|make it so|include|add|"
                   r"let |allow|able to|has to|have to|please|ensure|show|send|support|turn on|switch on)\b")
_SKIP = re.compile(r"(?i)^(hi|hey|hello|thanks|thank you|cheers|best|regards|by the way|funny story|"
                   r"fwiw|lol|ps\b|p\.s\.|urgent|asap|subject:)")
_ACTOR = re.compile(r"(?i)\b(?:our|the)\s+(bookkeepers?|accountants?|admins?|managers?|customers?|clients?|"
                    r"users?|owners?|staff|team members?|agents?|support agents?|members?)\b")


def _sentences(ask: str) -> list[str]:
    text = re.sub(r"\s+", " ", ask)
    return [s.strip(" -*•") for s in re.split(r"(?<=[.!?])\s+|\s+-\s+|\n", text) if s.strip()]


def respond(*, system: str | None, user: str, rng: Any) -> dict[str, Any]:
    m = re.search(r"<request>\s*(.*?)\s*</request>", user, re.DOTALL)
    ask = m.group(1) if m else user
    system = system or ""
    layered = "Agent context" in system and "<details>" in system
    precise = "words a tester can't check" in system
    flags_gaps = "Flag gaps" in system

    reqs = [s for s in _sentences(ask) if _CUES.search(s) and not _SKIP.match(s)]
    if reqs and rng.random() < 0.05:  # a little sampling noise
        reqs = reqs[:-1]
    reqs = reqs or ["Make the requested change described in the background"]
    actor_m = _ACTOR.search(ask)
    actor = actor_m.group(1).lower() if actor_m else None

    first = re.sub(r"(?i)^(can we|could we|we need to|please|make it so( that)?)\s+", "", reqs[0]).rstrip("?.!")
    title_words = first.split()[:9]
    title = " ".join(title_words)[:78].strip().capitalize() or "Requested change"
    if len(title.split()) < 3:
        title = f"Add requested change: {title}"

    ac = []
    for i, r in enumerate(reqs[:10]):
        item = r.rstrip("?")
        if not precise and i % 2 == 0:
            item += " and works correctly"
        ac.append(f"- [ ] {item}")
    summary = (f"{(actor or 'Users').capitalize()} need this change so the work described in the request is "
               f"possible without manual workarounds.")

    assumptions = []
    if flags_gaps and not actor:
        assumptions.append("The request doesn't say who the user is; assumed it is an internal team member.")

    background = " ".join(_sentences(ask))
    why = []
    if "## Why" in system:  # the guide asks for a Why section: the mock never invents one
        why = ["## Why", "Not stated in the request.", ""]
    parts = [f"# {title}", "", "**Type:** Story", "", *why, "## Summary", summary, "", "## Acceptance criteria", *ac, "",
             "## Out of scope", "- Changes not mentioned in the request", ""]
    if layered:
        parts += ["<details>", "<summary>Agent context</summary>", "", "### Background", background, ""]
        if assumptions:
            parts += ["### Assumptions", *[f"- {a}" for a in assumptions], ""]
        parts += ["</details>"]
    else:
        parts += ["## Background", background, ""]
        if assumptions:
            parts += ["## Assumptions", *[f"- {a}" for a in assumptions]]
    return {"ticket_markdown": "\n".join(parts).strip() + "\n"}


__all__ = ["respond"]


if __name__ == "__main__":  # pragma: no cover - quick look: python -m ticket_quality.eval_mock "ask text"
    import random
    import sys

    print(json.loads(json.dumps(respond(system="Agent context <details>", user=sys.argv[1], rng=random.Random(0))))
          ["ticket_markdown"])
