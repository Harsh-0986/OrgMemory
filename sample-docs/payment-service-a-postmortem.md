# Payment Service A: Postmortem and Migration Runbook

**Owner:** Lena Fischer (Payments)
**Status:** Draft, unreviewed
**Related:** ADR-0007 (LegacyPay adoption), ADR-0021 (Payments Modernisation)

## Summary

Between 12:40 and 13:05 UTC on 2026-09-14, the Checkout API returned elevated 5xx
rates for approximately 4% of requests. Cart Service and the Promotions Service were
affected because both sit downstream of Checkout. No data was lost and no payment was
double-captured.

This document is deliberately incomplete in one place. The cause of the incident is
recorded as "under investigation". Do not fill that gap from memory when writing
runbooks; the graph records the absence of a cause so the agent reports an unknown
rather than a guess.

## Impact

- Checkout API: 4% of requests returned 5xx for 25 minutes.
- Cart Service: degraded, because Cart depends on Checkout for price validation.
- Promotions Service: degraded, same path.
- Storefront Web: visible errors on the checkout page.
- Ledger Sync: unaffected. The batch path does not run during business hours.

## Timeline

| Time (UTC) | Event |
| --- | --- |
| 12:40 | Error rate on Checkout API rises above 2%. |
| 12:43 | Alert fires on the Checkout API error-budget burn. |
| 12:47 | Marcus Oyelaran paged. Investigates connection pool saturation. |
| 12:58 | Pool limit raised. Error rate begins falling. |
| 13:05 | Error rate back to baseline. Incident closed. |

## What we know and do not know

The connection pool on Checkout API saturated during a traffic spike. That part is
established: Marcus Oyelaran confirmed it in the traces, and the pool limit increase
reversed the symptom within seven minutes.

What we do not know is why the pool limit was set to its current value. There is no
recorded decision for the original configuration. ADR-0007 adopted LegacyPay for
payments processing but says nothing about pool sizing.

This is a genuine gap in the record, not an oversight to be papered over.

## Migration notes

The Payments Modernisation project is evaluating Payment Service B (PayFlow) as a
replacement for the current processor. PayFlow depends on the Fraud Scoring Gateway and
the Webhook Dispatcher, both of which are shared with the current processor. That shared
infrastructure has to support both paths during cutover.

Prerequisites before cutover:

1. Payment Service B (PayFlow) must be load-tested against the same peak traffic that
   caused this incident.
2. The connection pool limit must be re-derived, not copied from the current config.
3. Sign-off required from the owners of every service identified as downstream.

## Open questions

- Who owns the Fraud Scoring Gateway? This is not documented anywhere we could find.
- Does Payment Service B depend on the Identity & Access Service? The current processor
  does, and no one has confirmed either way for the replacement. If it does not, that
  is a security review item.
