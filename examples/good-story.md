# Send overdue-invoice reminders 3 days after the due date

**Type:** Story

## Why
Bookkeepers chase late payers by hand, and clients who aren't nudged pay later.

## Summary
Bookkeepers can switch on automatic email reminders for overdue invoices.

## Acceptance criteria
- [ ] A bookkeeper can turn automatic reminders on or off per client in Settings › Reminders
- [ ] The first reminder emails the client's billing contact 3 days after the invoice due date
- [ ] Further reminders go out every 7 days until the invoice is paid, up to 3 in total
- [ ] No reminder is sent for an invoice marked paid, even if payment arrives on the send day
- [ ] Each sent reminder appears in the invoice's activity log with date and recipient

## Out of scope
- SMS or Slack reminders
- Editing the reminder email template

<details>
<summary>Agent context</summary>

### Background
From the #bookkeeping thread: "most of our clients pay within a few days of the nudge, we just forget to send it."

### Assumptions
- Reminders use the existing billing-contact email on the client record.
- "Paid" means invoice status `paid` at send time.

### Implementation notes
- Daily job: extend `jobs/invoice_sweeps.py`; the email goes through `notifications/email.py`.
- Activity log entries: `InvoiceActivity(kind="reminder_sent")`.

</details>
