"""Splitting a request into one ticket per unit of work."""

import re
from pathlib import Path

from llm_evals.types import Case, Result
from typer.testing import CliRunner

from ticket_quality.cli import app
from ticket_quality.evals_plugin import TicketsSplit, output_of, request_sets

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evals" / "ticket-writing"


def case_with_two_requests() -> Case:
    atoms = [
        {"id": "a/a1", "set_id": "a", "keywords": ["csv", "invoice list"]},
        {"id": "a/a2", "set_id": "a", "keywords": ["90 days"]},
        {"id": "b/a1", "set_id": "b", "keywords": ["card", "payment link"]},
    ]
    return Case(id="c", input={"ask": "x"}, provenance="constructed", source={"atoms": atoms})


def ticket(title: str, *ac: str) -> str:
    items = "\n".join(f"- [ ] {a}" for a in ac)
    return f"# {title}\n\n## Summary\nSomething changes for someone.\n\n## Why\nNot stated in the request.\n\n" \
           f"## Acceptance criteria\n{items}\n"


def score(md: str):
    out = output_of(md)
    res = Result(run_id="r", case_id="c", version_id="v", sample_idx=0, output=out)
    return TicketsSplit(min_keyword_share=0.6, critical=False).score(case_with_two_requests(), res, None)


def test_one_ticket_per_request_passes():
    md = ticket("Export the invoice list as CSV", "The invoice list exports as a CSV file", "Only the last 90 days") \
        + "\n" + ticket("Pay invoices by card", "A customer can pay by card from a payment link")
    s = score(md)
    assert s.passed, s.reason


def test_merged_requests_fail_even_with_enough_tickets():
    md = ticket("Invoices: export and card payments", "The invoice list exports as a CSV file",
                "A customer can pay by card from a payment link") + "\n" + ticket("Limit to 90 days", "Only the last 90 days")
    s = score(md)
    assert not s.passed and "ticket(s) 1 hold requirements from separate requests" in s.reason


def test_merged_requests_fail():
    md = ticket("Invoices: export and card payments", "The invoice list exports as a CSV file",
                "Only the last 90 days", "A customer can pay by card from a payment link")
    s = score(md)
    assert not s.passed and "1 ticket(s) for 2" in s.reason


def test_splitting_one_request_into_parts_is_fine():
    md = ticket("Export invoices", "The invoice list exports as a CSV file") + "\n" + \
        ticket("Limit export to 90 days", "Only the last 90 days") + "\n" + \
        ticket("Pay invoices by card", "A customer can pay by card from a payment link")
    assert score(md).passed


def test_output_aggregates_across_tickets():
    out = output_of(ticket("A ticket title", "one") + "\n" + ticket("B ticket title", "two"))
    assert out["n_tickets"] == 2 and out["acceptance_criteria"] == ["one", "two"]


def test_hinted_atoms_and_sets():
    c = case_with_two_requests()
    c.source["atoms"].append({"id": "b/h", "set_id": "b", "keywords": ["audit"], "mode": "hinted"})
    assert {k: len(v) for k, v in request_sets(c).items()} == {"a": 2, "b": 1}


def test_cli_checks_each_ticket_in_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr("ticket_quality.judge.pick_backend", lambda backend="auto": None)
    f = tmp_path / "two.md"
    f.write_text(ticket("Export the invoice list as CSV", "The invoice list exports as a CSV file") + "\n" +
                 ticket("Pay invoices by card", "A customer can pay by card from a payment link"))
    res = CliRunner().invoke(app, ["check", str(f)])
    assert res.output.count("(ticket 1/2)") == 1 and res.output.count("(ticket 2/2)") == 1, res.output


def test_guide_examples_are_not_taken_from_test_cases():
    """Quoted examples in a writer guide must not appear in the eval's requests, or the
    eval would reward copying the example rather than following the rule."""
    cases = (SUITE / "data" / "atoms.jsonl").read_text().lower() + (SUITE / "data" / "real_asks.jsonl").read_text().lower()
    archived = {"writer-guide-v1.md", "writer-guide-v2.md", "writer-guide-v3.md"}  # written before this check
    archived_text = {(SUITE / "prompts" / n).read_text() for n in archived}
    for guide in [ROOT / "standard" / "writer-guide.md", *sorted((SUITE / "prompts").glob("writer-guide-v*.md"))]:
        if guide.name in archived or guide.read_text() in archived_text:
            continue
        for quote in re.findall(r'"([^"\n]{12,120})"', guide.read_text()):
            assert quote.lower() not in cases, f"{guide.name}: example {quote!r} appears in a test case"
