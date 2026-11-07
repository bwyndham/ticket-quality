---
name: review-ticket
description: Review an existing Jira or Linear ticket (or a pasted/drafted one) against the team's ticket standard using ticket-lint, explain what's vague or missing, and offer a rewrite that keeps the author's intent. Use when the user asks to review, check, validate, critique, lint or improve a ticket, issue, story or bug report, or gives an issue key like ENG-123 or PROJ-45 or a Linear/Jira link and asks whether it's good or ready.
---

# Review a ticket

`writer-guide.md` in this skill's folder is the team's standard. `ticket-lint` checks tickets against it.

## Workflow

1. **Run the checker.**
   - Issue key or link: `ticket-lint check <KEY-or-URL>`. Add `--tracker linear` or `--tracker jira` if it asks which.
   - Pasted text: write it to a temp file and run `ticket-lint check <file>`.
   - If you know the original request (a thread the user pasted), add `--ask <file>` for the faithfulness questions.
   - If ticket-lint isn't installed, or can't reach the tracker, review by hand against the guide's Rules section and say that's what you did.

2. **Report briefly.** The verdict, then the findings grouped as "Must fix" (errors) and "Worth fixing" (warnings), each in one line in plain words. Don't paste the raw output back.

3. **Offer a rewrite.** If anything failed, offer a rewritten ticket following `writer-guide.md`:
   - Keep the author's intent and every requirement they stated. Don't add requirements; where the original is vague, turn the gap into an open question instead of guessing.
   - Move background, implementation detail, file paths and logs into the collapsed agent context rather than deleting them.
   - Re-run `ticket-lint check` on the rewrite and show its verdict.

4. **Update the tracker only when asked**, using the Linear or Jira tool in this session.
