# Card retry charges the customer twice

**Type:** Bug

## Impact
Customers are charged twice for one order. Three were hit last week, all on mobile Safari, and each needs a manual refund.

## Summary
Retrying a declined card at checkout must charge the customer once.

## Steps to reproduce
1. On mobile Safari, check out with a card that declines once (Stripe test card 4000 0000 0000 0341)
2. Tap "Try again" when the decline message appears
3. Check the payments for the order in Stripe

## Expected
One successful charge for the order.

## Actual
Two successful charges about 2 seconds apart.

## Acceptance criteria
- [ ] Retrying after a decline creates at most one successful charge per order
- [ ] Double-tapping "Try again" sends one payment request

+++ Agent context
### Background
Support escalation, Zendesk #48213; order 100482 shows both charges.

### Implementation notes
- `PaymentIntent.create` is called twice from `checkout/retry.ts`; no idempotency key is passed.
- Trace: `payments/service.py` line 212, `StripeError: duplicate idempotency key not provided`.
+++
