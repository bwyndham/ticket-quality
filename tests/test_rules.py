from pathlib import Path

import pytest

from ticket_quality.rules import RULES, run_rules
from ticket_quality.standard import load_standard
from ticket_quality.ticket import parse_ticket
from ticket_quality.validate import validate

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
STD = load_standard()


def ids(findings, severity=None):
    return {f.rule for f in findings if severity is None or f.severity == severity}


def test_every_rule_in_the_standard_has_code_and_vice_versa():
    assert {r.id for r in STD.rules} == set(RULES)


@pytest.mark.parametrize("name", ["good-story.md", "good-bug-linear.md"])
def test_good_examples_pass_clean(name):
    report = validate(parse_ticket((EXAMPLES / name).read_text()), STD)
    assert report.verdict() == "PASS", [f.as_dict() for f in report.findings]


def test_vague_example_fails_for_the_right_reasons():
    report = validate(parse_ticket((EXAMPLES / "vague-story.md").read_text()), STD)
    assert report.verdict() == "FAIL"
    assert {"placeholders", "title_length", "ac_vague_language"} <= ids(report.findings, "error")
    assert {"title_vague", "agent_detail_in_human_section"} <= ids(report.findings, "warn")


def ticket(ac: list[str], summary="Bookkeepers need this so they stop chasing payments by hand.", title="Send reminders 3 days after due date", extra=""):
    body = "\n".join(f"- [ ] {a}" for a in ac)
    return parse_ticket(f"# {title}\n\n## Why\nThey chase late payers by hand.\n\n## Summary\n{summary}\n\n"
                        f"## Acceptance criteria\n{body}\n{extra}")


def test_numeric_terms_allowed_with_a_number():
    assert "ac_vague_language" not in ids(run_rules(ticket(["The page loads fast: under 2 seconds for 500 rows"]), STD))
    assert "ac_vague_language" in ids(run_rules(ticket(["The page loads fast"]), STD))


def test_always_vague_terms_fail_even_with_numbers():
    assert "ac_vague_language" in ids(run_rules(ticket(["All 3 reports work correctly"]), STD), "error")


def test_vague_terms_match_whole_words_only():
    # "fastest" / "cleanup" / "properly" inside other words shouldn't trip it.
    found = run_rules(ticket(["The highlighted row shows the invoice's due date"]), STD)
    assert "ac_vague_language" not in ids(found)


def test_human_section_budget_warns_then_fails():
    words = " ".join(["word"] * 210)
    warn = run_rules(ticket(["a happens"], summary=words), STD)
    assert any(f.rule == "human_section_budget" and f.severity == "warn" for f in warn)
    fail = run_rules(ticket(["a happens"], summary=" ".join(["word"] * 260)), STD)
    assert any(f.rule == "human_section_budget" and f.severity == "error" for f in fail)


def test_agent_context_words_dont_count_toward_budget():
    long_notes = " ".join(["note"] * 500)
    t = ticket(["a happens"], extra=f"\n<details><summary>Agent context</summary>\n{long_notes}\n</details>\n")
    assert "human_section_budget" not in ids(run_rules(t, STD))


def test_bug_needs_repro_fields():
    t = parse_ticket("# Search returns no results\n\n**Type:** Bug\n\n## Summary\nSearch is broken for everyone.\n\n"
                     "## Acceptance criteria\n- [ ] searching 'invoice' returns invoices\n")
    msgs = [f.message for f in run_rules(t, STD) if f.rule == "required_sections"]
    assert len(msgs) == 4  # impact, steps, expected, actual


def test_invalid_gherkin_and_missing_then():
    t = parse_ticket("# Release holds after a week\n\n## Summary\nMembers forget holds; release them.\n\n"
                     "## Acceptance criteria\nScenario: release\nGiven a hold\nWhen 7 days pass\n")
    assert "gherkin_valid" in ids(run_rules(t, STD), "error")


def test_valid_gherkin_passes():
    t = parse_ticket("# Release holds after a week\n\n## Summary\nMembers forget to collect holds, so release them.\n\n"
                     "## Acceptance criteria\n```gherkin\nScenario: release\nGiven a hold\nWhen 7 days pass\n"
                     "Then the hold is released\n```\n")
    assert "gherkin_valid" not in ids(run_rules(t, STD))


def test_agent_context_not_last_and_not_collapsed():
    t = parse_ticket("# Send reminders after due date\n\n## Summary\nBookkeepers chase payments by hand today.\n\n"
                     "## Acceptance criteria\n- [ ] x is sent\n\n<details><summary>Agent context</summary>n</details>\n\n"
                     "## Notes\nmore\n")
    assert "agent_context_placement" in ids(run_rules(t, STD))
    t2 = parse_ticket("# Send reminders after due date\n\n## Summary\nBookkeepers chase payments by hand today.\n\n"
                      "## Acceptance criteria\n- [ ] x is sent\n\n## Agent context\nnotes")
    assert any(f.rule == "agent_context_collapsed" and f.severity == "info" for f in run_rules(t2, STD))


def test_too_many_criteria_suggests_split():
    t = ticket([f"item {i} is shown" for i in range(12)])
    assert "ac_count" in ids(run_rules(t, STD), "warn")


def test_open_questions_warn():
    t = ticket(["x is shown"], extra="\n## Open questions\n- Which plan tiers get this?\n")
    assert "open_questions_unresolved" in ids(run_rules(t, STD), "warn")


def test_strict_turns_warnings_into_failure():
    t = ticket(["x is shown"], extra="\n## Open questions\n- Which plan tiers get this?\n")
    report = validate(t, STD)
    assert report.verdict() == "WARN" and report.verdict(strict=True) == "FAIL"


@pytest.mark.parametrize("item", [
    "The forecast includes all open invoices as expected cash inflows",
    "Reminders stop as soon as the invoice is marked paid",
    "After a bulk send, a summary shows how many invoices were sent",
])
def test_vague_terms_skip_ordinary_phrases(item):
    assert "ac_vague_language" not in ids(run_rules(ticket([item]), STD))


def test_as_expected_at_clause_end_still_fails():
    assert "ac_vague_language" in ids(run_rules(ticket(["The export works as expected."]), STD))


def test_stories_and_bugs_need_a_why_tasks_dont():
    body = "## Summary\nAn export button downloads orders.\n\n## Acceptance criteria\n- [ ] a CSV downloads\n"
    story = parse_ticket("# Add CSV export to orders\n\n**Type:** Story\n\n" + body)
    task = parse_ticket("# Upgrade lodash to 4.18\n\n**Type:** Task\n\n" + body)
    assert any("Why" in f.message for f in run_rules(story, STD) if f.rule == "required_sections")
    assert not [f for f in run_rules(task, STD) if f.rule == "required_sections"]


@pytest.mark.parametrize("heading", ["Why", "Impact", "Why this matters"])
def test_impact_and_why_are_the_same_section(heading):
    t = parse_ticket(f"# Add CSV export to orders\n\n## {heading}\nFinance re-types data.\n\n## Summary\nx y z w v\n")
    assert t.why == "Finance re-types data." and "re-types" not in t.summary


def test_not_stated_counts_as_present():
    t = parse_ticket("# Add CSV export to orders\n\n## Why\nNot stated in the request.\n\n## Summary\nAn export "
                     "button downloads orders.\n\n## Acceptance criteria\n- [ ] a CSV downloads\n")
    assert "required_sections" not in ids(run_rules(t, STD))
