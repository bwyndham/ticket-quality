---
name: write-ticket
description: Write a Jira or Linear ticket (story, bug or task) to the team's ticket standard - a short skimmable human section plus a collapsed agent context - and check it with ticket-lint before showing or filing it. Use whenever the user asks to write, draft, create, file or turn something into a ticket, issue, story, bug report or task, including from Slack threads, emails, meeting notes or the current conversation.
---

# Write a ticket

Follow `writer-guide.md` in this skill's folder exactly. It is the team's standard; this file only covers the workflow around it.

## Workflow

1. **Get the request.** Use what the user gave you (pasted thread, notes, conversation). If you're in a codebase and the ticket concerns it, look up the relevant code so the agent context's implementation notes are real, never guessed. Don't ask clarifying questions you could record as open questions instead; ask only if you can't tell what the ticket is about at all.

2. **Draft** the ticket following `writer-guide.md`. Pick the collapse syntax for where it's going:
   - Linear: `+++ Agent context` ... `+++`
   - Jira: an expand block if your Jira tool supports it, else `---` then `## Agent context` as the last section
   - unknown or just showing the user: `<details><summary>Agent context</summary>` ... `</details>`

3. **Check it** if `ticket-lint` is installed (`command -v ticket-lint`):
   - Write the draft to a temp file, and the original request to another.
   - Run `ticket-lint check <draft.md> --ask <request.txt>`.
   - Fix every `error`. Fix `warn` findings unless doing so would mean inventing something (for example, an unresolved open question stays an open question). At most two revise-and-recheck rounds.
   - If ticket-lint isn't installed, check the draft yourself against the guide's Rules section.

4. **Show the ticket** to the user, followed by one line: the ticket-lint verdict (or "not checked") and any warnings you deliberately left.

5. **File it only when asked.** Use the Linear or Jira tool available in this session: title in the title field, everything else as the description, the type as the issue type (Jira) or a `Bug` label for bugs (Linear). Then give the user the link. Don't file it in a tracker unless the user asks you to.

## Splitting

If the guide says the request should be split (unrelated pieces, or more than 10 criteria), say so and offer the split. Write the tickets one by one if the user agrees.
