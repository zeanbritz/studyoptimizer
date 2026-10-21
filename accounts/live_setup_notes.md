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
