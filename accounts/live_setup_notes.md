# StudiGarden production payments

Status: implementation prepared; real keys, real plans, public webhook delivery,
and the final live payment/cancellation check still need configuration. No
credentials or flags have been set by this code change. All live flags default off.

## Launch sequence (one existing Railway web service)

1. Run the full test suite and rebuild the Docker image. Commit reviewed files
   only, deploy with both live flags absent/False, and verify existing pages.
   The billing-policy page and contact details must be completed before enabling
   checkout. The approved voluntary guarantee is an automatic full refund of the
   first paid purchase requested within seven days, once per account. Statutory
   rights and exceptional refund cases remain separate from this guarantee.
2. Ensure Railway uses the image's default Docker CMD, `python -m
   config.web_runtime`. A custom Railway Start Command that invokes Gunicorn
   directly bypasses the billing worker; remove that override before activation.
   Keep the service running rather than sleeping while selling subscriptions.
3. In Paystack LIVE mode, create distinct monthly ZAR Grow (3500 cents/R35) and
   Bloom (9000 cents/R90) plans. Do not reuse the existing TEST plan codes.
4. Privately set Railway variables PAYSTACK_LIVE_SECRET_KEY (sk_live_...),
   PAYSTACK_LIVE_GROW_PLAN_CODE and PAYSTACK_LIVE_BLOOM_PLAN_CODE. Never put the
   key in Git, chat, a Docker build, or a public page. Keep DJANGO_DEBUG=False.
5. Set PAYSTACK_LIVE_ENABLED=True while keeping
   PAYSTACK_LIVE_CHECKOUT_ENABLED=False. Redeploy. Check logs show the live inbox
   worker is ready. Run `python manage.py check_paystack_live` via Railway SSH;
   it performs GETs only and verifies live mode, price, currency, and interval.
6. Register the LIVE webhook URL
   https://studigarden.com/payments/paystack/webhook/ for charge.success,
   subscription.create, subscription.not_renew, subscription.disable,
   invoice.create, invoice.update, and invoice.payment_failed. It requires an
   exact-body SHA-512 signature using this business's LIVE secret key. No tunnel.
7. Only when ready to accept real payments, explicitly enable
   PAYSTACK_LIVE_CHECKOUT_ENABLED=True. Check one authorised real checkout and
   cancellation end-to-end, including signed event receipt and processing, before
   advertising. A real checkout charges money; do not use test cards in LIVE mode.
   Confirm Grow and Bloom prices and the public refund/cancellation policy.
8. Enable PAYSTACK_LIVE_REFUNDS_ENABLED=True only after the guarantee workflow
   is verified and a working support contact is published. This exposes the
   self-service first-payment refund button. No business mailbox is needed for
   processing; the background worker handles the normal case automatically.

## Operation

The worker is an additional process in the same container, not another Railway
service. It adds RAM usage and a small database poll every 30 seconds; it does
not call Paystack when neither payment events nor refund requests await work. No Redis/Celery dependency
was added. If either the web process or worker dies, the container exits nonzero
so Railway's restart policy can recover it. Verify that restart policy.

The receiver records a sanitized, deduplicated event before responding. The
worker verifies provider state and transactions before granting paid time.
Retries survive deployments. Paid periods are absolute dates, not time added
each time a notification is redelivered. Cancellation preserves paid access and
study data; normal Free limits return when paid time ends. Beta access is kept.

To pause NEW sales, set only PAYSTACK_LIVE_CHECKOUT_ENABLED=False. Leave
PAYSTACK_LIVE_ENABLED and the worker on so verification, renewals and cancellation
continue. Turning off all billing while customers exist requires an explicit
operational plan, not just switching both flags off.

Review Paystack webhook delivery failures and the read-only Django webhook
receipt admin. A receipt remaining in Retry needs attention; do not manually
mark a payment successful or extend access without provider verification. Old
invoices no longer returned as most_recent_invoice are held for review rather
   than guessed. Disputes, exceptional refunds and missed-event recovery still
need operational review in Paystack. No new charges are created by this worker.

For the first launch, replacement/upgrade/restart checkout for an existing paid
customer is deliberately blocked to prevent overlapping subscriptions. Handle
those requests through support after checking the provider subscription. Do
not delete payment records to get around this guard.

The optional local webhook relay files are unrelated to production. They remain
strictly guarded for the disposable DEBUG/test-key/SQLite preview. The Cloudflare
tunnel is not used for live billing and can be stopped.

## Automatic first-payment refunds

PAYSTACK_LIVE_REFUNDS_ENABLED defaults False. It controls only NEW requests.
Accepted requests continue through the existing billing worker if this flag is
later switched off; do not disable PAYSTACK_LIVE_ENABLED while money returns are
still in progress. Apply migration 0016 before using the new refund code.

The customer signs in, confirms the refund in Profile, and the server records
the request time before waiting on database locks. The worker checks the first
owned, verified LIVE checkout against Paystack's actual paid_at timestamp and
the seven-day deadline. No usage test, reason, or manual approval is required.
One request per account/payment is enforced in the database. Renewals do not
qualify for this voluntary automatic guarantee; statutory rights remain intact.

The worker stops the matching provider subscription first. It then commits a
submission intent BEFORE the full-refund POST. If that POST times out or the
process restarts, it only looks up refunds for that exact transaction; it never
blindly repeats a money-return POST. Uncertain submissions unresolved after a
day, partial/manual refund conflicts, and provider failures need attention.
Normal pending refunds are checked every two minutes without customer action.
Paystack needs-attention cases can require bank details: these cannot honestly
be promised zero human intervention. Exceptional cases appear in the read-only
StudyRefund admin and worker logs; no new mailbox is needed for the normal flow.

Only provider-confirmed completion marks the payment reversed and removes its
paid entitlement. Beta privileges, another funded entitlement, and all saved
study data are preserved. Never delete a refund/payment record to retry a POST.

The operator has approved zd.britz@icloud.com as the temporary public support
and refund contact; it is the default STUDIGARDEN_SUPPORT_EMAIL. No branded
mailbox, email forwarding or DNS change is needed for this contact. A configured
STUDIGARDEN_SUPPORT_EMAIL overrides it, including an explicitly blank value.
Only change to a future branded address after it actually receives mail. This
does not change the Mailgun sender or automatic refund behaviour. Complete
legal/operator details and review all public terms before launch.
The other draft terms still need their operator/account/dispute details completed
and reviewed. No live key, real refund, deployment, or external setting was used
while implementing/testing this feature.

## Replacing an unfinished checkout

Apply migration 0017 before starting this version. Profile and Pricing share one
card template and stylesheet. Their POST forms identify the unfinished checkout
the customer saw. Choosing a plan reconciles that reference first, then marks
an unpaid attempt discarded and opens a new reference. In-flight or unverifiable
payments remain protected; stale forms/double clicks do not discard the new
replacement. Never delete the old payment records or assume their provider links
have been voided.

A later verified charge on a discarded reference creates a separate durable
StudyRefund with reason discarded_checkout. The existing live billing worker
stops only the proven old subscription and submits its full refund. It never
applies the discarded charge to membership, changes the chosen plan, or consumes
the account's once-only first-payment guarantee. This recovery continues even
when new checkout or new voluntary refund requests are paused.

Canonical invoice transaction IDs distinguish same-plan subscriptions. Only when
no competing checkout for that customer/plan exists may a single canonical
subscription created near the verified payment time be used. Never guess between
subscriptions or cancel any subscription currently linked to a membership.
Ambiguous/provider-unavailable matches retry, then require attention after 24
hours. Partial refunds, uncertain refund POSTs and bank-detail failures follow
the same existing no-blind-retry rules. Exceptional cases are visible in Profile,
the read-only refund admin (filter by reason/status), and worker logs; there is
no claim of zero manual intervention. Keep the live webhook and billing worker
running. No extra scheduled service is required.

# Plan changes: backend in progress, not customer-enabled yet

`PAYSTACK_LIVE_PLAN_CHANGES_ENABLED` defaults to `False`. Leave it disabled.
The saved change records and quotes alone do not change billing or access.
Customer routes have NOT been connected. Do not call backend entry points from
a shell against real accounts or enable this flag as a workaround.

Agreed policy: an upgrade charges the full new monthly price and starts its new
billing period after verified payment; refund the lower plan's verified payment
funding the current billing period, once. A downgrade keeps the already-paid
higher access until its paid-through date, then bills the lower monthly amount.
Free has no future debit. Dates are billing periods, not calendar-month resets.
The old subscription must be stopped safely, and ambiguous financial requests
must be reconciled before any further submission. Do not guess ownership or
blindly repeat a subscription-create or refund POST after a timeout.

The upgrade backend now records a new checkout reference before contacting the
provider. An unpaid checkout leaves Grow untouched. A canonically verified new
Bloom charge starts a fresh paid month. The existing live worker then stops the
exact historical Grow subscription and queues its funding payment (including a
verified renewal) in the durable refund outbox, independently of the first-
payment guarantee. It never uses the current Bloom membership's cancel method
to refund Grow. Accepted work continues if new plan changes/refunds are paused.
Uncertain cancellations/refund submissions are reconciled with GET requests;
unresolved ownership or financial states require attention, not a blind retry.

This is not a launchable switching feature yet. Scheduled downgrades, cancellation
and resumption of scheduled billing, retired-subscription renewal races, customer
consent/status controls, and public policy text still need implementation and
testing before enabling customer switches. No new migration is needed beyond
0018 for this upgrade-backend checkpoint. No real payment/refund was submitted
while implementing or testing it.

## Scheduled downgrade scheduler checkpoint (still disabled)

Apply migration 0019 before this scheduler is used. It adds a one-way identity
fingerprint to plan-change records, not a reusable authorisation or a card token.
Existing records receive a blank fingerprint and are not silently approved for
new recurring billing. A paid downgrade records the exact previously charged
card, target plan/price and first-debit date. The worker processor confirms the
old renewal is stopped while preserving its paid-through time, commits submission
intent, and creates the lower subscription with that explicit future start date.
An ambiguous POST is GET-reconciled against customer, plan, amount, start date,
authorisation fingerprint, creation time and the pre-submission subscription
baseline. It is never automatically repeated. Ambiguous or incomplete matches
require attention. No subscription-create request is made for Free.

The downgrade processor is NOT registered in the live worker or customer routes
at this checkpoint. First-debit reconciliation, safe cancellation/resumption of
scheduled billing, and refund/account-change cleanup must be connected before it
can run for real customers. Merely creating a subscription never grants Grow
access. Leave PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False; do not call the backend
from a production shell. Existing live checkout and cancellation remain unchanged.
All scheduling tests use a fake provider; no actual subscription was created.

## Verified lower payments and cancellation (migration 0020)

Migration 0020 adds cancellation request/completion timestamps and links recovery
refunds to their saved plan changes. The live worker NOW processes accepted
downgrades, superseding the disconnected-worker note above. Customer plan-switch
entry points remain disconnected. Leave PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False;
do not deploy this checkpoint alone or call the backend from a production shell.

Subscription metadata never grants Grow. The canonical invoice and verified
transaction must agree on mode, customer, plan, price, IDs and absolute billing
period. Only a successful debit replaces Bloom; failures preserve remaining paid
higher access. The first scheduled debit becomes explicit proof for subsequent
renewals, cancellation, upgrades and a later move to Free. Replays never add time.

Cancellation records the server request time and confirms BOTH the old and
scheduled renewals have stopped. An uncertain subscription-create POST is GET-
reconciled, never blindly repeated. Explicitly cancelling a switch can instead
resume the higher plan while its paid month and next debit date are confirmed.
Default cancellation never silently resumes paid billing. The normal Cancel plan
button also handles scheduled replacements; Profile must not report all renewals
stopped while a replacement is pending. Ownership/confirmation failures need attention.

A debit before cancellation keeps its funded month even if its notification is
delayed. Debits after cancellation, early scheduled charges and verified renewals
on replaced billing enter the durable full-refund recovery outbox, without
overwriting or cancelling the chosen plan. Only one financial request per payment
is allowed. Ambiguous refund POSTs are never repeated. Guarantee eligibility checks
pause a switch without cancelling it; approved guarantees stop replacement billing
before submitting the refund. No reusable card or cancellation token is persisted.

Remaining work: customer consent/status/switch controls, paid-plan restart/resume
controls, matching policy text and a final end-to-end check. All checks so far
use a fake provider and disposable database. No live financial changes were made.

## Customer plan-change controls (after migration 0020; no new migration)

Profile and the shared Pricing cards now link funded paid members to explicit
upgrade/downgrade confirmations. This supersedes the disconnected-entry-point
note above, but NOT the rollout restriction: leave
PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False. Nothing was deployed or enabled here.

GET only renders server-derived terms, without gateway calls or billing records.
POST needs CSRF, explicit consent and a signed 15-minute confirmation bound to
the owned membership, email, configured plans, target, price and billing date.
The services recheck the snapshot under the user lock before billing actions.
Grow -> Bloom continues one unique checkout; Bloom -> Grow and paid -> Free
record worker instructions and never report unconfirmed scheduling as complete.

Scheduled-change cancellation has separate, owned confirmations: stop both future
renewals, or explicitly keep the original plan renewing while the funded period
and canonical price/date are still valid. Stopping accepted billing remains
available if new sales/switching is paused. Keeping paid renewal requires the
switching and checkout gates. The worker rechecks price/date before and after
enable and refuses refunded funding. Provider details/tokens are not rendered.

Profile displays upgrade credits/recovery refunds separately from the first-
payment guarantee. Public policy text describes the same upgrade, downgrade,
freeze and confirmation rules, and says switching is not enabled while paused.
Legacy/new Free checkout and cancellation routes retain their existing gates.

Still intentionally unsupported: a standalone resumption after cancellation and
paid restart after expiry. Those choices cannot bypass the old-subscription and
payment-history guards. Finish their backend/customer controls and verify real
provider response shapes/end-to-end behaviour before rollout. Automated tests use
fake providers and disposable databases, not actual cards or subscriptions.

## Resume and restart controls (no new migration)

Standalone resumption and expired-plan restart are now connected to the same
signed consent routes. This supersedes the unsupported-resume/restart note above.
Keep PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False until provider-shape/end-to-end
verification and an explicitly approved rollout. No keys/flags/deployments were
changed, and no real provider account was mutated during implementation.

Resumption records a durable queued instruction for the SAME subscription. It
adds no payment or paid time. The worker confirms the exact price and next debit
before/after enable; a timeout is GET-reconciled, never a new subscription create.
Expired dates, refunded funding and ambiguous ownership fail closed. Pending
renewal invoices wait for the accepted resume to reconcile. Accepted work may
finish when NEW switching/sales is paused; global live billing must remain on.

Restart requires canonical history/ownership, an expired funded period and no
unfinished payment/refund/change. Refunded history requires its completed refund
and is ownership proof ONLY, never entitlement or a fresh refund guarantee. The
previous subscription is confirmed stopped durably before opening checkout with
one unique reference. New paid access comes only from verified full-price payment,
with absolute new-month dates. Generic Free checkout guards were not weakened.
New same-tier subscription linkage requires an exact canonical invoice/TX link;
delayed metadata cannot attach the retired subscription to the new membership.

Cancel plan retires pending resume/restart instructions under the same user lock,
stops the previous renewal, and discards an unpaid restart's ledger reference.
A late payment on that reference is refunded separately, not applied as access.
Retired old renewal charges enter recovery without cancelling the chosen new plan.
Inactive/beta/conflicting accounts never gain access from a restart payment.
Profile and billing copy distinguish accepted requests, confirmation and paid time.

Tests still use fake provider responses/disposable databases. The remaining
rollout check must verify actual provider response shapes and the full enabled
customer flow before these new controls are advertised or enabled.

## Confirmed LIVE subscription response compatibility

A read-only production lookup confirmed subscription.domain="live" while both
embedded customer.domain and plan.domain are omitted/null. The actual subscription
notification was retained for retry as provider_ownership_invalid; its charge was
already verified. The shared subscription matcher now accepts those redundant
nested modes as omitted/null, just as it already did for the embedded customer.
It still requires explicit subscription mode, exact verified customer/plan codes,
valid subscription identity and rejects any explicit conflicting nested mode.
Canonical standalone plan and transaction mode/price checks remain unchanged.

Regression tests replay the failed-metadata outcome with the confirmed response
shape and assert only the subscription link changes: no extra payment, refund,
paid-time extension or provider mutation. Existing upgrade, scheduling, restart
and renewal fixtures now exercise omitted embedded plan modes as well.
No production receipt was edited or manually linked here; after a reviewed
deployment, the existing worker can reprocess its retained retry normally.
Keep PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False during that verification.
