# ticket-quality

One definition of a good ticket, used three ways:

| | What | How |
|---|---|---|
| **Check** | Lint any ticket, whether you wrote it or Claude did, in Linear, Jira or a file | `ticket-lint check ENG-123` |
| **Write** | Claude writes tickets to the standard and checks its own draft | the `write-ticket` / `review-ticket` skills |
| **Measure** | Every change to how Claude writes is gated: PROMOTE / HOLD / ROLLBACK | the [llm-evals](https://github.com/bwyndham/llm-evals) suite in `evals/ticket-writing` |

```
standard/
  ticket-standard.yaml   rules a program checks (sections, word budget, vague words, ...)
  rubric.yaml            questions a judge model answers (testable? skimmable? self-contained?)
  writer-guide.md        how Claude writes tickets: the skills ship it, the eval measures it
  judge/*.jinja          judge prompts, shared by ticket-lint and the eval
        │
        ├── ticket-lint check       rules + one judge call → PASS / WARN / FAIL with fixes
        ├── skills/                 write-ticket, review-ticket (installed into ~/.claude/skills)
        └── evals/ticket-writing    72 requests → writer guide → same rules + same rubric → gate
```

## The standard in one paragraph

**One ticket per unit of work**: a request that holds separate pieces of work becomes separate tickets, however it arrived, and one feature can be split into parts that ship on their own. Each ticket has **two layers**. The **human section** comes first: title, a short summary (what changes, for whom), a **Why** for stories or **Impact** for bugs (tasks are exempt; never invented, "Not stated in the request" plus an open question when there's no reason), acceptance criteria, out of scope and open questions, around 180 words and never more than 220. The **agent context** comes last and collapsed: background, assumptions, implementation notes, file paths, logs. It's useful to an agent or the engineer doing the work, and kept away from everyone else. Acceptance criteria are pass/fail and never rest on words like "intuitive", "works correctly" or "fast" without a number. Read `standard/` for the full version; it's a draft for you to edit.

## Setup

```bash
uv sync                                    # Python 3.11+
cp .env.example .env                       # ANTHROPIC_API_KEY, LINEAR_API_KEY, JIRA_* as needed
uv tool install --editable .               # puts `ticket-lint` on your PATH, reading this repo's standard/
ticket-lint install-skills                 # write-ticket + review-ticket → ~/.claude/skills
```

### API key or Claude subscription

Every model call (the judge in `ticket-lint`, and the eval runs) can go through either backend:

- **Your Claude subscription (Pro/Max)**: through the `claude` CLI in headless mode, with no API billing. `ticket-lint` uses it automatically when `ANTHROPIC_API_KEY` isn't set. Eval runs use it with `--provider claude-code`, a built-in llm-evals provider. Each call runs with Claude Code's own prompt, tools, settings and MCP servers turned off, so the model sees only your prompt, just as with the API. Calls count against your plan's usage limits. If you hit one, the run stops with a clear message instead of recording failures. Reported costs are list-price equivalents, not charges.
- **An API key**: set `ANTHROPIC_API_KEY`; evals use it with `--provider anthropic` (the default), and `ticket-lint --backend api` forces it. CI always uses the API key.

## Check tickets

```bash
ticket-lint check ENG-123                          # Linear (LINEAR_API_KEY)
ticket-lint check https://acme.atlassian.net/browse/PROJ-9   # Jira (JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)
ticket-lint check draft.md --ask slack-thread.txt  # also checks it against the request it came from
pbpaste | ticket-lint check -                      # several tickets? each starts with its own # Title
ticket-lint check ENG-1 ENG-2 ENG-3 --no-judge     # rules only: free and instant
ticket-lint check ENG-123 --strict --format json   # warnings fail too; machine-readable
ticket-lint standard                               # print every rule and rubric question
```

```
FAIL  examples/vague-story.md  "Improve dashboard"  [story]
   human section 97 words · 3 AC (checklist) · agent context: none
   ✗ error placeholders (rule): Unfinished placeholder(s) in the human section: TBD.
           fix: Fill them in, or turn each unknown into an open question.
   ✗ error ac_vague_language (rule): AC 2 uses untestable wording (user-friendly, intuitive): ...
   ! warn  agent_detail_in_human_section (rule): File paths in the human section: services/dashboard/queries.py, ...
```

The rubric judge adds its findings to the same list, marked `(judge)`. It runs on your API key if one is set, otherwise on your Claude subscription through the `claude` CLI (about 20 seconds per ticket). It's one `claude-sonnet-5-5` call per ticket and the result is cached, so rechecking an unchanged ticket costs nothing. Exit code 0 = pass (warnings allowed), 1 = a ticket failed, 2 = couldn't run. Bare keys like `ENG-123` go to whichever tracker is configured. If both are, pass `--tracker` or set `TICKET_LINT_TRACKER`. Jira descriptions (ADF) are converted to Markdown, expand blocks included. If your acceptance criteria live in a custom field, set `JIRA_AC_FIELD`.

## Have Claude write them

Once the skills are installed, ask Claude Code to "write a ticket for this" or "turn this thread into a Linear issue". `write-ticket` follows `writer-guide.md`, splits the request into one ticket per unit of work, runs `ticket-lint check` on its drafts, fixes errors (at most two rounds), shows you the ticket and its verdict, and files it through your Linear/Jira tools only when you ask. `review-ticket` does the reverse for existing tickets: "review ENG-123" gives the findings and offers a rewrite that keeps the author's intent and moves detail into the agent context.

Agent context collapses per tracker: `+++ Agent context` … `+++` in Linear, an expand block in Jira (or a final `## Agent context` section if your Jira tool can't make one), `<details>` everywhere else. The parser recognises all of them.

## Measure changes to the writer

`evals/ticket-writing` runs the writer guide against 72 requests: 60 synthetic ones with known requirements (vague, bundled, urgent, missing the user) and 12 realistic ones. It checks the output with the same rules and rubric `ticket-lint` uses:

| Check | Gates? | Catches |
|---|---|---|
| `ticket_structure` | yes, critical | missing sections (including Why/Impact), placeholders, broken Gherkin |
| `tickets_split` | yes | two separate requests merged into one ticket |
| `ticket_skimmable` | yes | human section over budget, detail not in agent context |
| `ticket_precise` | yes | topic titles, untestable criteria |
| `requirements_covered` (llm-evals built-in) | yes | a stated requirement that no ticket title or acceptance criterion states |
| `gaps_flagged` | yes | a missing user or implied need not flagged |
| `checklist` (judge, rubric.yaml) | after calibration | everything that needs reading comprehension |

```bash
uv run llm-evals estimate evals/ticket-writing             # calls, tokens and time before running anything
uv run llm-evals gate evals/ticket-writing --candidate versions/seeded_inline_detail.yaml \
    --provider mock --skip-judges                          # offline wiring check: ROLLBACK, exit 2
uv run llm-evals gate evals/ticket-writing --candidate versions/v2.yaml \
    --provider claude-code --skip-judges                   # a real comparison, on your subscription
uv run llm-evals aa evals/ticket-writing --runs 5 --provider claude-code   # measure noise before trusting the 5-pt tolerance
```

**To try a change to the guide**, gate it locally on your subscription: copy the guide to `evals/ticket-writing/prompts/writer-guide-vN.md`, edit it, add a `versions/vN.yaml` pointing at it, and run `uv run llm-evals gate evals/ticket-writing --candidate versions/vN.yaml --provider claude-code --skip-judges`. On PROMOTE, copy it over `standard/writer-guide.md` (the baseline, `versions/current.yaml`, points there), run `uv run llm-evals promote evals/ticket-writing versions/current.yaml` and `ticket-lint install-skills`, and open a PR. CI (`.github/workflows/ticket-evals.yml`) runs the tests; its eval gate runs only if the repo has an `ANTHROPIC_API_KEY` secret, and otherwise skips itself with a PR comment pointing back to the local run.

**To make the judge count**, label its answers: run a gate without `--skip-judges`, then `uv run llm-evals calibration serve --db evals/ticket-writing/.evals/evals.sqlite` (or `calibration label ... --check checklist`). Once a rubric question has ~50 labels and agrees with you (Cohen's κ ≥ 0.6), it gates. Until then it's reported only. Rewording a question resets its calibration, so settle the wording first.

## Making it yours

1. **Edit the standard.** `standard/` is a first draft. Change thresholds in `ticket-standard.yaml`, add or remove questions in `rubric.yaml` and keep `writer-guide.md` consistent. A new rule needs a function in `src/ticket_quality/rules.py`; the tests flag a mismatch.
2. **Replace the realistic cases** in `evals/ticket-writing/data/real_asks.jsonl` with real (anonymised) requests from your teams. A few dozen good ones beat hundreds of synthetic ones.
3. **Run `ticket-lint` over a batch of your team's existing tickets** (`--no-judge --format json`) to see where the thresholds bite before you enforce anything.

## Limits

- The judge and the eval use Claude only (llm-evals is Claude-only), through the API or the `claude` CLI.
- The eval measures the writer guide as a single prompt. The skill's check-and-revise loop runs on top of that in Claude Code and isn't itself measured.
- The Linear `+++` toggle and Jira expand blocks depend on what your Linear/Jira tool sends. If they don't collapse, the `## Agent context` heading fallback still passes (with a note).
- The tracker integrations are tested against recorded API shapes, not live accounts. Try `ticket-lint check` on one real issue of each first.
