from ticket_quality.ticket import parse_ticket

LINEAR_TOGGLE = """# Add CSV export to the orders page

## Summary
Finance screenshots the orders table today; they need a CSV of what they're looking at.

## Acceptance criteria
- [ ] An "Export CSV" button on the orders page downloads the rows matching the current filters
- [ ] The CSV has columns order id, date, customer, total and status

+++ Agent context
### Assumptions
- Export is limited to users who can already see the orders page.
### Implementation notes
- Reuse `OrdersQuery` from api/orders.py.
+++
"""


def test_linear_toggle_is_collapsed_agent_context():
    t = parse_ticket(LINEAR_TOGGLE)
    assert t.title == "Add CSV export to the orders page"
    assert t.agent_context_style == "collapsed" and t.agent_context_last
    assert "OrdersQuery" in t.agent_context and "OrdersQuery" not in t.human_markdown
    assert t.ac_format == "checklist" and len(t.acceptance_criteria) == 2
    assert t.assumptions == ["Export is limited to users who can already see the orders page."]


def test_details_block_and_content_after_it():
    md = ("# Title words here\n\n## Summary\nWhy it matters for someone.\n\n## Acceptance criteria\n- [ ] x happens\n\n"
          "<details><summary>Agent context</summary>\n\nnotes\n</details>\n\n## Out of scope\n- y\n")
    t = parse_ticket(md)
    assert t.agent_context_style == "collapsed"
    assert t.agent_context_last is False
    assert t.out_of_scope == ["y"]


def test_heading_agent_context_runs_to_end_and_drops_divider():
    md = "# A title here\n\nSome summary text.\n\n## Acceptance criteria\n- [ ] a\n\n---\n## Agent context\nlots of notes\n## More\nstill agent"
    t = parse_ticket(md)
    assert t.agent_context_style == "heading"
    assert "still agent" in t.agent_context
    assert t.summary == "Some summary text."
    assert not t.human_markdown.rstrip().endswith("---")


def test_non_agent_details_stays_in_human_section():
    md = "# T t t\n\n## Summary\ns\n\n<details><summary>Screenshots</summary>img</details>\n"
    t = parse_ticket(md)
    assert t.agent_context is None and "Screenshots" in t.human_markdown


def test_gherkin_criteria():
    md = ("# Hold release\n\n## Acceptance criteria\n```gherkin\nScenario: Released\nGiven a hold\nWhen 7 days pass\n"
          "Then the hold is released\n\nScenario: Kept\nGiven a hold\nWhen 2 days pass\nThen it stays\n```\n")
    t = parse_ticket(md)
    assert t.ac_format == "gherkin" and len(t.acceptance_criteria) == 2
    assert t.acceptance_criteria[0].startswith("Scenario: Released")


def test_bug_fields_and_type_line():
    md = ("# Retry double charges\n\n**Type:** Bug\n\n## Summary\nCharged twice.\n\n## Steps to reproduce\n1. Decline\n"
          "2. Retry\n\n## Expected\nOne charge\n\n## Actual\nTwo charges\n\n## Acceptance criteria\n- [ ] one charge\n")
    t = parse_ticket(md)
    assert t.type == "bug"
    assert t.steps_to_reproduce == ["Decline", "Retry"]
    assert t.expected == "One charge" and t.actual == "Two charges"
    assert "Type" not in t.summary


def test_jira_style_bold_headings_and_tracker_title():
    md = "Users can't find old reports.\n\n**Acceptance Criteria:**\n* reports older than 90 days are searchable\n"
    t = parse_ticket(md, title="Search reports older than 90 days", ticket_type="Story")
    assert t.title == "Search reports older than 90 days"
    assert t.summary == "Users can't find old reports."
    assert t.acceptance_criteria == ["reports older than 90 days are searchable"]


def test_type_inferred_as_bug_from_fields():
    t = parse_ticket("# Search returns nothing\n\n## Actual\nempty list\n")
    assert t.type == "bug"


def test_empty_markers_ignored():
    t = parse_ticket("# A b c\n\n## Open questions\n- None\n")
    assert t.open_questions == []


def test_split_tickets_on_titles_only():
    from ticket_quality.ticket import parse_tickets, split_tickets

    md = ("intro line\n# First ticket title\n\n## Summary\nA.\n\n<details><summary>Agent context</summary>\n\n"
          "# not a ticket\n\n</details>\n\n```\n# not a ticket either\n```\n\n# Second ticket title\n\n## Summary\nB.\n")
    chunks = split_tickets(md)
    assert len(chunks) == 2 and chunks[0].startswith("# First ticket title")
    assert [t.title for t in parse_tickets(md)] == ["First ticket title", "Second ticket title"]


def test_one_title_is_one_ticket():
    from ticket_quality.ticket import split_tickets

    assert split_tickets("# Only one\n\n## Summary\nx\n") == ["# Only one\n\n## Summary\nx\n"]
    assert len(split_tickets("no title at all")) == 1
