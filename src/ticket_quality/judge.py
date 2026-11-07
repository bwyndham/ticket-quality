"""The rubric judge for `ticket-lint check`: one model call per ticket.

It reuses llm-evals' JudgeClient (same prompt templates, same response parsing,
same SQLite cache) so a ticket graded here and the same ticket graded inside the
eval suite get the same treatment. Only the rubric items that apply are sent:
`bug` items for bugs, `with_ask` items when the original request is given.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from ticket_quality.rules import Finding
from ticket_quality.standard import RubricItem, Standard
from ticket_quality.ticket import Ticket

DEFAULT_MODEL = "claude-sonnet-5-5"
CACHE_PATH = Path(os.environ.get("TICKET_LINT_CACHE", Path.home() / ".cache" / "ticket-lint" / "judge.sqlite"))


class ItemVerdict(BaseModel):
    id: str
    answer: Literal["yes", "no"]
    reason: str = ""
    fix: str = ""


class Verdicts(BaseModel):
    items: list[ItemVerdict]


def applicable_items(standard: Standard, ticket: Ticket, *, has_ask: bool) -> list[RubricItem]:
    out = []
    for item in standard.rubric:
        if item.applies == "bug" and ticket.type != "bug":
            continue
        if item.applies == "with_ask" and not has_ask:
            continue
        out.append(item)
    return out


def build_payload(items: list[RubricItem], ticket: Ticket, ask: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"task": "checklist", "items": [{"id": i.id, "question": i.question} for i in items],
                               "ticket": ticket.judge_view()}
    if ask:
        payload["ask"] = ask
    return payload


def pick_backend(backend: str = "auto") -> str | None:
    """api (ANTHROPIC_API_KEY), claude-code (the claude CLI, on your subscription), or None."""
    import shutil

    if backend == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "api"
        return "claude-code" if (os.environ.get("CLAUDE_BIN") or shutil.which("claude")) else None
    if backend not in ("api", "claude-code"):
        raise ValueError(f"backend must be auto, api or claude-code, not {backend!r}")
    return backend


def make_client(model: str | None = None, provider: Any | None = None, cache_path: Path | None = CACHE_PATH,
                backend: str = "api"):
    from llm_evals.judges.client import JudgeClient

    if provider is None and backend == "claude-code":
        from ticket_quality.claude_code import ClaudeCodeProvider

        provider = ClaudeCodeProvider()
    elif provider is None:
        from llm_evals.runners.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider()
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    return JudgeClient(provider, model=model or os.environ.get("TICKET_LINT_JUDGE_MODEL", DEFAULT_MODEL),
                       cache_path=cache_path)


def judge_ticket(ticket: Ticket, standard: Standard, client: Any, *, ask: str | None = None) -> list[Finding]:
    """Findings for every rubric item answered "no" (or skipped by the judge)."""
    items = applicable_items(standard, ticket, has_ask=bool(ask))
    if not items:
        return []
    result = client.judge(standard.judge_system_path, standard.judge_user_path, {},
                          build_payload(items, ticket, ask), Verdicts)
    answers = {v.id: v for v in result.parsed.items}
    findings = []
    for item in items:
        v = answers.get(item.id)
        if v is None:
            findings.append(Finding(rule=item.id, severity="warn", source="judge",
                                    message="The judge gave no answer for this item."))
        elif v.answer == "no":
            findings.append(Finding(rule=item.id, severity=item.severity, source="judge",
                                    message=v.reason.strip() or item.question, fix=v.fix.strip()))
    return findings


__all__ = ["DEFAULT_MODEL", "applicable_items", "build_payload", "judge_ticket", "make_client", "pick_backend"]
