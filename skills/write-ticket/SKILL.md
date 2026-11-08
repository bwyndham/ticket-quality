---
name: write-ticket
description: Write Jira or Linear tickets (stories, bugs, tasks) to the team's ticket standard - one ticket per unit of work, each a short skimmable human section plus a collapsed agent context - and check them with ticket-lint before showing or filing them. Use whenever the user asks to write, draft, create, file or turn something into a ticket, issue, story, bug report or task, including from Slack threads, emails, meeting notes or the current conversation.
---

# Write a ticket

Follow `writer-guide.md` in this skill's folder exactly. It is the team's standard; this file only covers the workflow around it.

## Workflow

1. **Get the request.** Use what the user gave you (pasted thread, notes, conversation). If you're in a codebase and the ticket concerns it, look up the relevant code so the agent context's implementation notes are real, never guessed. Don't ask clarifying questions you could record as open questions instead; ask only if you can't tell what the ticket is about at all.

2. **Decide the units of work.** A request that holds several separate pieces of work becomes several tickets, one per unit, as `writer-guide.md` describes, even if it arrived as one message. Say up front how you split it ("This is two pieces of work, so two tickets: …").

3. **Draft** each ticket following `writer-guide.md`. Pick the collapse syntax for where it's going:
   - Linear: `+++ Agent context` ... `+++`
   - Jira: an expand block if your Jira tool supports it, else `---` then `## Agent context` as the last section
   - unknown or just showing the user: `<details><summary>Agent context</summary>` ... `</details>`

4. **Check them** if `ticket-lint` is installed (`command -v ticket-lint`):
   - Write all the tickets to one temp file, one after another (each starts with its own `# Title`), and the original request to another.
   - Run `ticket-lint check <draft.md> --ask <request.txt>`. It checks each ticket, with the others as context for whether the request is fully covered.
   - Fix every `error`. Fix `warn` findings unless doing so would mean inventing something (for example, an unresolved open question stays an open question). At most two revise-and-recheck rounds.
   - If ticket-lint isn't installed, check the draft yourself against the guide's Rules section.

5. **Show the tickets** to the user, each followed by one line: its ticket-lint verdict (or "not checked") and any warnings you deliberately left.

6. **File them only when asked.** Use the Linear or Jira tool available in this session, one issue per ticket: title in the title field, everything else as the description, the type as the issue type (Jira) or a `Bug` label for bugs (Linear). If the tool can link issues, link tickets from the same request as related. Then give the user the links. Don't file anything in a tracker unless the user asks you to.

If the user wants them combined after all, they can say so; don't merge separate units of work on your own.
