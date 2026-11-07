"""`ticket-lint`: check tickets against the standard, and install the Claude skills.

    ticket-lint check ENG-123                      # a Linear or Jira issue
    ticket-lint check https://acme.atlassian.net/browse/PROJ-9
    ticket-lint check draft.md --ask request.txt   # a file, judged against the request it came from
    pbpaste | ticket-lint check -                  # stdin
    ticket-lint check ENG-1 ENG-2 --no-judge       # rules only: free, offline, instant
    ticket-lint standard                           # print the standard
    ticket-lint install-skills                     # write-ticket + review-ticket into ~/.claude/skills

Exit codes: 0 pass (warnings allowed), 1 at least one ticket failed, 2 couldn't run.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer

from ticket_quality.standard import REPO_ROOT, load_standard
from ticket_quality.ticket import Ticket, parse_ticket
from ticket_quality.validate import Report, validate

app = typer.Typer(help="Check Jira/Linear tickets against your ticket standard.", no_args_is_help=True,
                  add_completion=False)


def _load_dotenv() -> None:
    for path in (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if key and value and key not in os.environ:
                os.environ[key] = value


def _read_text_arg(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    p = Path(value)
    return p.read_text(encoding="utf-8") if p.is_file() else value


def load_ticket(ref: str, *, tracker: Optional[str], title: Optional[str], ticket_type: Optional[str]) -> Ticket:
    """A ticket from stdin, a file (.md/.txt, or .json from the eval suite or an API), or a tracker."""
    if ref == "-":
        return parse_ticket(sys.stdin.read(), title=title, ticket_type=ticket_type, source={"file": "stdin"})
    path = Path(ref)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
            md = data.get("ticket_markdown") or data.get("markdown") or data.get("description") or ""
            return parse_ticket(md, title=title or data.get("title"), ticket_type=ticket_type or data.get("type"),
                                source={"file": str(path)})
        return parse_ticket(text, title=title, ticket_type=ticket_type, source={"file": str(path)})
    from ticket_quality.trackers import fetch, resolve

    resolved = resolve(ref, tracker)
    if resolved is None:
        raise typer.BadParameter(f"{ref!r} is not a file, '-', an issue key or a Linear/Jira URL")
    fetched = fetch(*resolved)
    return parse_ticket(fetched.markdown, title=title or fetched.title,
                        ticket_type=ticket_type or fetched.type, source=fetched.source)


_ICON = {"error": "✗", "warn": "!", "info": "·"}
_COLOR = {"PASS": typer.colors.GREEN, "WARN": typer.colors.YELLOW, "FAIL": typer.colors.RED}


def render_text(report: Report, strict: bool) -> str:
    t, v = report.ticket, report.verdict(strict)
    ident = t.source.get("id") or t.source.get("file") or ""
    lines = [typer.style(f"{v}", fg=_COLOR[v], bold=True) + f"  {ident}  \"{t.title or '(no title)'}\"  [{t.type}]"]
    s = report.stats
    agent = {"collapsed": "collapsed ✓", "heading": "heading (not collapsed)", "none": "none"}[s["agent_context"]]
    lines.append(f"   human section {s['human_words']} words · {s['acceptance_criteria']} AC ({s['ac_format']}) · "
                 f"agent context: {agent}")
    for f in report.findings:
        tag = "judge" if f.source == "judge" else "rule"
        lines.append(f"   {_ICON[f.severity]} {f.severity:<5} {f.rule} ({tag}): {f.message}")
        if f.fix:
            lines.append(f"           fix: {f.fix}")
    if not report.findings:
        lines.append("   no findings")
    if report.judge_note:
        lines.append(f"   note: {report.judge_note}")
    elif not report.judged:
        lines.append("   note: rules only (no judge)")
    return "\n".join(lines)


@app.command()
def check(
    refs: list[str] = typer.Argument(..., help="Files, '-' for stdin, issue keys (ENG-123) or Linear/Jira URLs."),
    tracker: Optional[str] = typer.Option(None, help="linear or jira, when an issue key could be either."),
    ask: Optional[str] = typer.Option(None, help="The request the ticket was written from: a file, '-' or text. "
                                                 "Adds the faithfulness questions."),
    judge: Optional[bool] = typer.Option(None, "--judge/--no-judge",
                                         help="Run the rubric judge (default: on when a backend is available)."),
    backend: str = typer.Option("auto", help="Judge backend: api (ANTHROPIC_API_KEY), claude-code (the claude CLI, "
                                             "billed to your Claude subscription) or auto (api if a key is set, else claude-code)."),
    strict: bool = typer.Option(False, help="Fail on warnings too."),
    fmt: str = typer.Option("text", "--format", help="text or json."),
    ticket_type: Optional[str] = typer.Option(None, "--type", help="story, bug or task (default: from the tracker or the ticket)."),
    title: Optional[str] = typer.Option(None, help="Title, when the file doesn't have a '# Title' line."),
    standard: Optional[Path] = typer.Option(None, help="Standard folder (default: this repo's standard/)."),
    model: Optional[str] = typer.Option(None, help="Judge model (default claude-sonnet-5-5)."),
) -> None:
    """Check one or more tickets against the standard."""
    _load_dotenv()
    std = load_standard(standard)
    ask_text = _read_text_arg(ask)
    from ticket_quality.judge import make_client, pick_backend

    chosen = pick_backend(backend)
    use_judge = judge if judge is not None else chosen is not None
    if use_judge and chosen is None:
        raise typer.BadParameter("no judge backend: set ANTHROPIC_API_KEY or install the claude CLI")
    client = make_client(model, backend=chosen) if use_judge else None
    reports, any_fail, errors = [], False, 0
    for ref in refs:
        try:
            ticket = load_ticket(ref, tracker=tracker, title=title, ticket_type=ticket_type)
        except Exception as exc:  # noqa: BLE001 - report and move on to the next ref
            typer.secho(f"ERROR  {ref}: {exc}", fg=typer.colors.RED, err=True)
            errors += 1
            continue
        report = validate(ticket, std, judge_client=client, ask=ask_text)
        any_fail |= report.verdict(strict) == "FAIL"
        reports.append(report)
        if fmt == "text":
            typer.echo(render_text(report, strict) + "\n")
    if fmt == "json":
        out = [r.as_dict(strict) for r in reports]
        typer.echo(json.dumps(out[0] if len(out) == 1 else out, indent=2))
    if errors and not reports:
        raise typer.Exit(2)
    raise typer.Exit(1 if any_fail else 0)


@app.command("standard")
def show_standard(standard: Optional[Path] = typer.Option(None, help="Standard folder.")) -> None:
    """Print the rules and rubric questions the checker uses."""
    std = load_standard(standard)
    typer.echo(f"Standard: {std.dir}\n\nRules (checked by code):")
    for r in std.rules:
        typer.echo(f"  {r.severity:<5} {r.group:<9} {r.id}: {r.what}")
    typer.echo("\nRubric (checked by the judge):")
    for i in std.rubric:
        scope = "" if i.applies == "always" else f" [{i.applies}]"
        typer.echo(f"  {i.severity:<5} {i.id}{scope}: {i.question}")


SKILLS = ("write-ticket", "review-ticket")


def install_skills_to(dest: Path, standard_path: Path | None = None) -> list[Path]:
    """Copy the skills, each with the current writer guide as `writer-guide.md`."""
    std = load_standard(standard_path)
    written = []
    for name in SKILLS:
        src = REPO_ROOT / "skills" / name
        target = dest / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)
        shutil.copy(std.writer_guide_path, target / "writer-guide.md")
        written.append(target)
    return written


@app.command("install-skills")
def install_skills(
    dest: Path = typer.Option(Path.home() / ".claude" / "skills", help="Skills folder."),
    standard: Optional[Path] = typer.Option(None, help="Standard folder."),
) -> None:
    """Install the write-ticket and review-ticket Claude skills (rerun after editing the standard)."""
    for path in install_skills_to(dest, standard):
        typer.echo(f"installed {path}")


def main() -> None:  # pragma: no cover
    app()
