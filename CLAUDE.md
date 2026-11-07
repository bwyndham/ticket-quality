# ticket-quality

One ticket standard, used three ways: `ticket-lint` checks any Jira/Linear ticket, the
`write-ticket` / `review-ticket` skills make Claude write and review to it, and the
llm-evals suite in `evals/ticket-writing` gates changes to how Claude writes.

- The standard is `standard/`: `ticket-standard.yaml` (rules, checked by code),
  `rubric.yaml` (questions, checked by a judge), `writer-guide.md` (what Claude follows;
  also the eval suite's system prompt), `judge/*.jinja` (judge prompts, shared by
  ticket-lint and the eval). Change them together.
- Every rule id in `ticket-standard.yaml` needs a function in `src/ticket_quality/rules.py`
  (a test enforces it). Thresholds belong in the YAML, not the code.
- `writer-guide.md` is rendered as a Jinja template by the eval: never put `{{`, `{%` or `{#` in it.
- One parser (`ticket.py`) for every source; tracker adapters only fetch and convert to Markdown.
- Run tests with `uv run pytest`. They never call a model or a tracker.
- After changing the guide or skills, `uv run ticket-lint install-skills` refreshes ~/.claude/skills.
