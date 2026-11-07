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

A ticket has **two layers**. The **human section** comes first: title, a 1–3 sentence summary (what, for whom, why), acceptance criteria, out of scope and open questions, under about 150 words, so it reads in 30 seconds. The **agent context** comes last and collapsed: background, assumptions, implementation notes, file paths, logs. It's useful to an agent or the engineer doing the work, and kept away from everyone else. Acceptance criteria are pass/fail and never rest on words like "intuitive", "works correctly" or "fast" without a number. Read `standard/` for the full version; it's a draft for you to edit.

## Setup

```bash
uv sync                                    # Python 3.11+
cp .env.example .env                       # ANTHROPIC_API_KEY, LINEAR_API_KEY, JIRA_* as needed
uv tool install --editable .               # puts `ticket-lint` on your PATH, reading this repo's standard/
ticket-lint install-skills                 # write-ticket + review-ticket → ~/.claude/skills
```

### API key or Claude subscription

Every model call (the judge in `ticket-lint`, and the eval runs) can go through either backend:

- **Your Claude subscription (Pro/Max)**: through the `claude` CLI in headless mode, with no API billing. `ticket-lint` uses it automatically when `ANTHROPIC_API_KEY` isn't set. For evals, use `ticket-evals` in place of `llm-evals`; it takes the same commands and flags. Each call runs with Claude Code's own prompt, tools, settings and MCP servers turned off, so the model sees only your prompt, just as with the API. Calls count against your plan's usage limits. If you hit one, the run stops with a clear message instead of recording failures. Reported costs are list-price equivalents, not charges.
- **An API key**: set `ANTHROPIC_API_KEY`, then use `llm-evals` (or `TICKET_EVALS_BACKEND=api ticket-evals`). `ticket-lint --backend api` forces it. CI always uses the API key.

## Check tickets

```bash
ticket-lint check ENG-123                          # Linear (LINEAR_API_KEY)
ticket-lint check https://acme.atlassian.net/browse/PROJ-9   # Jira (JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)
ticket-lint check draft.md --ask slack-thread.txt  # also checks it against the request it came from
pbpaste | ticket-lint check -
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

Once the skills are installed, ask Claude Code to "write a ticket for this" or "turn this thread into a Linear issue". `write-ticket` follows `writer-guide.md`, runs `ticket-lint check` on its draft, fixes errors (at most two rounds), shows you the ticket and its verdict, and files it through your Linear/Jira tools only when you ask. `review-ticket` does the reverse for existing tickets: "review ENG-123" gives the findings and offers a rewrite that keeps the author's intent and moves detail into the agent context.

Agent context collapses per tracker: `+++ Agent context` … `+++` in Linear, an expand block in Jira (or a final `## Agent context` section if your Jira tool can't make one), `<details>` everywhere else. The parser recognises all of them.

## Measure changes to the writer

`evals/ticket-writing` runs the writer guide against 72 requests: 60 synthetic ones with known requirements (vague, bundled, urgent, missing the user) and 12 realistic ones. It checks the output with the same rules and rubric `ticket-lint` uses:

| Check | Gates? | Catches |
|---|---|---|
| `ticket_structure` | yes, critical | missing sections, placeholders, broken Gherkin |
| `ticket_skimmable` | yes | human section over budget, detail not in agent context |
| `ticket_precise` | yes | topic titles, untestable criteria |
| `covers_ask` | yes | a stated requirement with no acceptance criterion |
| `gaps_flagged` | yes | a missing user or implied need not flagged |
| `checklist` (judge, rubric.yaml) | after calibration | everything that needs reading comprehension |

```bash
ticket-evals estimate evals/ticket-writing                   # calls, tokens and time before running anything
ticket-evals gate evals/ticket-writing --candidate versions/seeded_inline_detail.yaml \
    --provider mock --skip-judges                            # offline wiring check: ROLLBACK, exit 2
ticket-evals gate evals/ticket-writing --candidate versions/v2.yaml --skip-judges   # a real comparison, on your subscription
ticket-evals aa evals/ticket-writing --runs 5                # measure noise before trusting the 5-pt tolerance
```

**To try a change to the guide**, open a PR that edits `standard/writer-guide.md` (or the model in `versions/current.yaml`). `.github/workflows/ticket-evals.yml` runs the base branch's guide against yours and comments with the decision. Add the `ANTHROPIC_API_KEY` repo secret first.

**To make the judge count**, label its answers: run a gate without `--skip-judges`, then `ticket-evals calibration serve --db evals/ticket-writing/.evals/evals.sqlite` (or `calibration label ... --check checklist`). Once a rubric question has ~50 labels and agrees with you (Cohen's κ ≥ 0.6), it gates. Until then it's reported only. Rewording a question resets its calibration, so settle the wording first.

## Making it yours

1. **Edit the standard.** `standard/` is a first draft. Change thresholds in `ticket-standard.yaml`, add or remove questions in `rubric.yaml` and keep `writer-guide.md` consistent. A new rule needs a function in `src/ticket_quality/rules.py`; the tests flag a mismatch.
2. **Replace the realistic cases** in `evals/ticket-writing/data/real_asks.jsonl` with real (anonymised) requests from your teams. A few dozen good ones beat hundreds of synthetic ones.
3. **Run `ticket-lint` over a batch of your team's existing tickets** (`--no-judge --format json`) to see where the thresholds bite before you enforce anything.

## Limits

- The judge and the eval use Claude only (llm-evals is Claude-only), through the API or the `claude` CLI.
- The eval measures the writer guide as a single prompt. The skill's check-and-revise loop runs on top of that in Claude Code and isn't itself measured.
- The Linear `+++` toggle and Jira expand blocks depend on what your Linear/Jira tool sends. If they don't collapse, the `## Agent context` heading fallback still passes (with a note).
- The tracker integrations are tested against recorded API shapes, not live accounts. Try `ticket-lint check` on one real issue of each first.
