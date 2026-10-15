"""Synthetic seed dataset for OrgMemory.

Everything here is invented for demonstration. The company ("Northwind
Logistics") is fictional, as are every person, service, incident, and decision.

Design notes
------------
**Dependency direction.** `(A)-[:DEPENDS_ON]->(B)` means "A depends on B", so a
breakage in B propagates *into* A. Impact analysis therefore traverses
DEPENDS_ON edges **backwards**, from the changed service out to everything that
depends on it. Getting this backwards is the single easiest way to produce a
confidently wrong answer, so the traversal queries are explicit about it.

**Evidence discipline.** `Incident -[:CAUSED_BY]->` is only asserted where the
source material would support it. Where an incident's cause is genuinely unknown,
the dataset records the incident as AFFECTED-only rather than inventing a
cause - the agent must be able to demonstrate saying "we don't know".
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------

PEOPLE: list[dict[str, Any]] = [
    {
        "id": "per-amara-osei",
        "name": "Amara Osei",
        "role": "Staff Engineer, Payments",
        "team": "Payments",
        "email": "amara.osei@northwind.example",
        "tenure_months": 74,
    },
    {
        "id": "per-diego-ruiz",
        "name": "Diego Ruiz",
        "role": "Engineering Manager, Payments",
        "team": "Payments",
        "email": "diego.ruiz@northwind.example",
        "tenure_months": 61,
    },
    {
        "id": "per-priya-raman",
        "name": "Priya Raman",
        "role": "Principal Engineer, Payments",
        "team": "Payments",
        "email": "priya.raman@northwind.example",
        "tenure_months": 96,
    },
    {
        "id": "per-lena-fischer",
        "name": "Lena Fischer",
        "role": "Senior Engineer, Checkout",
        "team": "Checkout",
        "email": "lena.fischer@northwind.example",
        "tenure_months": 52,
    },
    {
        "id": "per-sofia-ivanova",
        "name": "Sofia Ivanova",
        "role": "Senior Engineer, Billing",
        "team": "Billing",
        "email": "sofia.ivanova@northwind.example",
        "tenure_months": 45,
    },
    {
        "id": "per-tom-berg",
        "name": "Tom Berg",
        "role": "Senior SRE, Platform",
        "team": "Platform",
        "email": "tom.berg@northwind.example",
        "tenure_months": 88,
    },
    {
        "id": "per-marcus-oyelaran",
        "name": "Marcus Oyelaran",
        "role": "Engineer, Fraud & Risk",
        "team": "Fraud & Risk",
        "email": "marcus.oyelaran@northwind.example",
        "tenure_months": 33,
    },
    {
        "id": "per-james-whitfield",
        "name": "James Whitfield",
        "role": "Staff Engineer, Identity",
        "team": "Identity",
        "email": "james.whitfield@northwind.example",
        "tenure_months": 102,
    },
    {
        "id": "per-noah-adeyemi",
        "name": "Noah Adeyemi",
        "role": "Tech Lead, Web",
        "team": "Web Platform",
        "email": "noah.adeyemi@northwind.example",
        "tenure_months": 29,
    },
    {
        "id": "per-aya-nakamura",
        "name": "Aya Nakamura",
        "role": "Staff Engineer, Data Platform",
        "team": "Data Platform",
        "email": "aya.nakamura@northwind.example",
        "tenure_months": 67,
    },
]

# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

SERVICES: list[dict[str, Any]] = [
    {
        "id": "svc-payment-legacy",
        "name": "Payment Service A (LegacyPay)",
        "description": (
            "Primary payment processor integration handling all card capture, "
            "authorisation and settlement for Northwind checkout."
        ),
        "criticality": "critical",
        "language": "Java",
        "tier": "1",
        "monthly_active_calls": 4200000,
        "vendor": "LegacyPay",
    },
    {
        "id": "svc-payment-v2",
        "name": "Payment Service B (PayFlow)",
        "description": (
            "Next-generation payment service built on the PayFlow SDK. Currently "
            "no production traffic; used only in the modernisation pilot."
        ),
        "criticality": "medium",
        "language": "Go",
        "tier": "unproven",
        "monthly_active_calls": 0,
        "vendor": "PayFlow",
    },
    {
        "id": "svc-checkout",
        "name": "Checkout API",
        "description": "Orchestrates cart validation, fraud screening and payment capture.",
        "criticality": "critical",
        "language": "Java",
        "tier": "1",
        "monthly_active_calls": 5100000,
        "vendor": "internal",
    },
    {
        "id": "svc-cart",
        "name": "Cart Service",
        "description": "Holds active shopping carts and drives checkout submission.",
        "criticality": "high",
        "language": "Java",
        "tier": "2",
        "monthly_active_calls": 6800000,
        "vendor": "internal",
    },
    {
        "id": "svc-storefront",
        "name": "Storefront Web",
        "description": "Customer-facing web storefront rendering carts and checkout.",
        "criticality": "high",
        "language": "TypeScript",
        "tier": "2",
        "monthly_active_calls": 9200000,
        "vendor": "internal",
    },
    {
        "id": "svc-promo",
        "name": "Promotions Service",
        "description": "Applies discount and promotion codes to cart contents.",
        "criticality": "medium",
        "language": "Go",
        "tier": "3",
        "monthly_active_calls": 2400000,
        "vendor": "internal",
    },
    {
        "id": "svc-order",
        "name": "Order Service",
        "description": "Creates and tracks orders once payment is authorised.",
        "criticality": "critical",
        "language": "Java",
        "tier": "1",
        "monthly_active_calls": 3900000,
        "vendor": "internal",
    },
    {
        "id": "svc-invoice",
        "name": "Invoice & Billing Service",
        "description": "Generates customer invoices and reconciles payment capture.",
        "criticality": "critical",
        "language": "Java",
        "tier": "1",
        "monthly_active_calls": 310000,
        "vendor": "internal",
    },
    {
        "id": "svc-subscription",
        "name": "Subscription Service",
        "description": "Recurring billing plans and dunning retries.",
        "criticality": "high",
        "language": "Ruby",
        "tier": "2",
        "monthly_active_calls": 780000,
        "vendor": "internal",
    },
    {
        "id": "svc-refunds",
        "name": "Refunds Service",
        "description": "Processes full and partial refunds against captured payments.",
        "criticality": "high",
        "language": "Java",
        "tier": "2",
        "monthly_active_calls": 96000,
        "vendor": "internal",
    },
    {
        "id": "svc-ledger",
        "name": "General Ledger Sync",
        "description": "Batches captured payment events into the finance general ledger.",
        "criticality": "critical",
        "language": "Python",
        "tier": "1",
        "monthly_active_calls": 4100000,
        "vendor": "internal",
    },
    {
        "id": "svc-fraud",
        "name": "Fraud Scoring Gateway",
        "description": "Single entry point for pre-authorisation risk scoring.",
        "criticality": "high",
        "language": "Python",
        "tier": "2",
        "monthly_active_calls": 4200000,
        "vendor": "internal",
    },
    {
        "id": "svc-analytics",
        "name": "Analytics Pipeline",
        "description": "Batch feature pipeline feeding fraud model training.",
        "criticality": "low",
        "language": "Python",
        "tier": "3",
        "monthly_active_calls": 9000,
        "vendor": "internal",
    },
    {
        "id": "svc-webhook",
        "name": "Webhook Dispatcher",
        "description": "Fans payment lifecycle events out to downstream consumers.",
        "criticality": "medium",
        "language": "Go",
        "tier": "2",
        "monthly_active_calls": 8600000,
        "vendor": "internal",
    },
    {
        "id": "svc-notification",
        "name": "Notification Service",
        "description": "Sends transactional email, SMS and push notifications.",
        "criticality": "medium",
        "language": "Go",
        "tier": "3",
        "monthly_active_calls": 1200000,
        "vendor": "internal",
    },
    {
        "id": "svc-identity",
        "name": "Identity & Access Service",
        "description": "Issues service tokens and authenticates employee access.",
        "criticality": "critical",
        "language": "Java",
        "tier": "1",
        "monthly_active_calls": 31000000,
        "vendor": "internal",
    },
    {
        "id": "svc-search",
        "name": "Product Search",
        "description": "Catalog search and autocomplete for storefront and cart.",
        "criticality": "medium",
        "language": "Java",
        "tier": "2",
        "monthly_active_calls": 7400000,
        "vendor": "internal",
    },
    {
        "id": "svc-inventory",
        "name": "Inventory Service",
        "description": "Tracks stock availability and reservations per warehouse.",
        "criticality": "high",
        "language": "Go",
        "tier": "2",
        "monthly_active_calls": 5600000,
        "vendor": "internal",
    },
]

# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

PROJECTS: list[dict[str, Any]] = [
    {
        "id": "proj-payments-modernization",
        "name": "Payments Modernisation",
        "status": "in_progress",
        "summary": (
            "Replace the LegacyPay integration with the PayFlow-based Payment "
            "Service B before the LegacyPay API v3 sunset."
        ),
        "started": "2025-08-01",
        "team_size": 6,
    },
    {
        "id": "proj-checkout-v3",
        "name": "Checkout V3 Rollout",
        "status": "completed",
        "summary": "Split checkout orchestration into a dedicated service with timeouts.",
        "started": "2023-05-01",
        "team_size": 4,
    },
    {
        "id": "proj-fraud-gateway",
        "name": "Unified Fraud Gateway",
        "status": "completed",
        "summary": "Consolidated fraud scoring entry points behind one gateway.",
        "started": "2025-01-15",
        "team_size": 5,
    },
    {
        "id": "proj-ledger-realtime",
        "name": "Real-time Ledger Streaming",
        "status": "proposed",
        "summary": "Replace 15-minute batch ledger sync with an event stream.",
        "started": "2026-01-10",
        "team_size": 3,
    },
    {
        "id": "proj-webhook-hardening",
        "name": "Webhook Delivery Hardening",
        "status": "completed",
        "summary": "Added signed webhooks, retries and dead-letter handling.",
        "started": "2024-09-01",
        "team_size": 3,
    },
]

# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------
# Note: `inc-unknown-webhook-latency` deliberately has an AFFECTED edge but no
# CAUSED_BY edge, so the agent can demonstrate reporting an unresolved cause.

INCIDENTS: list[dict[str, Any]] = [
    {
        "id": "inc-2025-07-legacypay-key-rotation",
        "title": "LegacyPay API key rotation broke checkout webhooks",
        "severity": "sev1",
        "occurred_at": "2025-07-14T09:22:00Z",
        "summary": (
            "LegacyPay rotated its API signing key without notice. Checkout "
            "webhook verification failed for 41 minutes, stalling order creation "
            "for roughly 18,000 carts. Resolved by coordinating a key rotation "
            "window with the vendor."
        ),
        "root_cause_known": True,
        "duration_minutes": 41,
    },
    {
        "id": "inc-2024-11-ledger-drift",
        "title": "General ledger drift after reconciliation backlog",
        "severity": "sev2",
        "occurred_at": "2024-11-03T22:05:00Z",
        "summary": (
            "A ledger batch job stalled for six hours, leaving captured payments "
            "unreconciled and producing incorrect customer invoices. Finance "
            "reported 1,240 mismatched invoices."
        ),
        "root_cause_known": True,
        "duration_minutes": 360,
    },
    {
        "id": "inc-2025-03-fraud-timeout",
        "title": "Fraud gateway timeouts degraded checkout completion",
        "severity": "sev2",
        "occurred_at": "2025-03-22T16:40:00Z",
        "summary": (
            "Fraud scoring p99 latency exceeded the checkout deadline during a "
            "traffic spike, causing checkout abandonment to rise from 8% to 23%."
        ),
        "root_cause_known": True,
        "duration_minutes": 95,
    },
    {
        "id": "inc-2025-09-checkout-degradation",
        "title": "Checkout degradation during peak freight sale",
        "severity": "sev3",
        "occurred_at": "2025-09-18T11:30:00Z",
        "summary": (
            "Checkout connection pool exhausted under peak load. Cart submission "
            "fails returned 5xx for 22 minutes."
        ),
        "root_cause_known": True,
        "duration_minutes": 22,
    },
    {
        "id": "inc-2026-02-payflow-sandbox-idempotency",
        "title": "PayFlow sandbox rejected idempotent retries",
        "severity": "sev3",
        "occurred_at": "2026-02-11T13:10:00Z",
        "summary": (
            "During the modernisation pilot, Payment Service B returned a "
            "duplicate-charge error when a capture request was retried. No "
            "customer impact - sandbox only."
        ),
        "root_cause_known": True,
        "duration_minutes": 120,
    },
    {
        "id": "inc-2026-04-webhook-latency",
        "title": "Elevated webhook delivery latency to downstream consumers",
        "severity": "sev3",
        "occurred_at": "2026-04-02T06:15:00Z",
        "summary": (
            "Webhook delivery p95 rose to 4.2 minutes for roughly two hours. "
            "Customer impact was not confirmed and the triggering change has not "
            "been identified."
        ),
        "root_cause_known": False,
        "duration_minutes": 125,
    },
]

# --------------------------------------------------------------------------
# Architecture decisions
# --------------------------------------------------------------------------

DECISIONS: list[dict[str, Any]] = [
    {
        "id": "dec-2023-06-legacypay-adoption",
        "title": "Adopt LegacyPay as the primary payment processor",
        "date": "2023-06-14",
        "rationale": (
            "LegacyPay offered the fastest integration path and kept us inside "
            "PCI SAQ-A scope, avoiding cardholder data on our own infrastructure. "
            "At the time it was the only processor meeting our three-day launch "
            "requirement. No analysis of processor portability was performed."
        ),
        "status": "superseded",
        "decision_makers": ["per-priya-raman", "per-diego-ruiz"],
    },
    {
        "id": "dec-2025-08-payments-modernization",
        "title": "Modernise the payment stack and evaluate PayFlow as a replacement",
        "date": "2025-08-05",
        "rationale": (
            "LegacyPay has announced an API v3 sunset in Q4 2026, which forces a "
            "migration regardless of preference. PayFlow offers lower per-transaction "
            "cost, native multi-currency, and 3DS step-up authentication that "
            "LegacyPay only supports through a third-party add-on. We committed to "
            "building Payment Service B against PayFlow before the sunset deadline."
        ),
        "status": "accepted",
        "decision_makers": ["per-diego-ruiz", "per-priya-raman", "per-amara-osei"],
    },
    {
        "id": "dec-2024-02-retain-batch-ledger-sync",
        "title": "Retain 15-minute batch ledger sync instead of real-time events",
        "date": "2024-02-19",
        "rationale": (
            "Finance requires a reconciled general ledger before period close. "
            "Batch sync met this requirement with a known worst-case drift of 15 "
            "minutes, which was accepted as an explicit trade-off against the "
            "operational cost of real-time streaming."
        ),
        "status": "accepted",
        "decision_makers": ["per-tom-berg", "per-sofia-ivanova"],
    },
    {
        "id": "dec-2025-05-unified-fraud-gateway",
        "title": "Route all payment fraud scoring through a single gateway",
        "date": "2025-05-08",
        "rationale": (
            "Checkout and the legacy payment integration were calling the fraud "
            "model directly with divergent rules. Consolidating behind one gateway "
            "removed inconsistent decline behaviour and gave a single place to "
            "enforce latency budgets."
        ),
        "status": "accepted",
        "decision_makers": ["per-marcus-oyelaran", "per-lena-fischer"],
    },
    {
        "id": "dec-2026-01-dual-write-migration",
        "title": "Adopt a shadow-traffic dual-write migration strategy",
        "date": "2026-01-22",
        "rationale": (
            "A big-bang cutover carries unacceptable risk for 4.2M monthly payment "
            "calls. We will shadow real traffic to Payment Service B, compare "
            "authorisation results, and only then shift the primary write path. "
            "Cutover requires sign-off from the owners of every service that depends "
            "on the payment path."
        ),
        "status": "proposed",
        "decision_makers": ["per-amara-osei", "per-priya-raman", "per-lena-fischer"],
    },
]

# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "doc-legacypay-integration-runbook",
        "title": "LegacyPay Integration Runbook",
        "source_type": "runbook",
        "source_uri": "https://wiki.northwind.example/runbooks/legacypay-integration",
        "content": (
            "Payment Service A communicates with LegacyPay over the v2 REST API "
            "using HMAC-signed requests. Capture is synchronous; settlement is "
            "asynchronous via signed webhooks. Webhook signing keys are shared "
            "with the vendor and rotate roughly annually - coordinate any rotation "
            "window with the Checkout team. Partial refunds are issued through a "
            "separate endpoint and are not idempotent."
        ),
    },
    {
        "id": "doc-payflow-gap-analysis",
        "title": "Payment Service B Gap Analysis",
        "source_type": "analysis",
        "source_uri": "https://wiki.northwind.example/projects/payments/gap-analysis",
        "content": (
            "PayFlow parity assessment against the LegacyPay integration. NOT YET "
            "IMPLEMENTED: multi-currency settlement, 3DS step-up authentication, "
            "split tender payments, and partial refunds. SUPPORTED: card capture, "
            "async settlement via webhooks, idempotency keys on capture. The team "
            "estimates multi-currency is roughly six weeks of work. Until these gaps "
            "close, Payment Service B cannot replace Payment Service A for all "
            "traffic, because Invoice & Billing relies on partial refunds and "
            "Subscription Service relies on recurring multi-currency billing."
        ),
    },
    {
        "id": "doc-adr-0007-legacy-adoption",
        "title": "ADR-0007: LegacyPay adoption rationale",
        "source_type": "adr",
        "source_uri": "https://wiki.northwind.example/adr/0007-legacypay-adoption",
        "content": (
            "Records the original decision to adopt LegacyPay. Key trade-off "
            "accepted at the time: fastest time-to-market and reduced PCI scope, in "
            "exchange for tight coupling to a single vendor's v2 API."
        ),
    },
    {
        "id": "doc-adr-0021-payments-modernization",
        "title": "ADR-0021: Payments modernisation",
        "source_type": "adr",
        "source_uri": "https://wiki.northwind.example/adr/0021-payments-modernization",
        "content": (
            "Authorises Payment Service B as the successor to Payment Service A. "
            "Explicitly acknowledges that the migration is a vendor-risk exercise as "
            "much as a feature exercise, and that the LegacyPay v3 sunset sets the "
            "deadline independently of business preference."
        ),
    },
    {
        "id": "doc-migration-runbook-draft",
        "title": "Payment Migration Runbook (draft)",
        "source_type": "runbook",
        "source_uri": "https://wiki.northwind.example/runbooks/payment-migration-draft",
        "content": (
            "Draft migration checklist. Steps still to be confirmed: shadow traffic "
            "comparison harness, webhook signing key rollout, refund parity testing, "
            "and a rollback runbook. Requires sign-off from owners of Checkout, "
            "Invoice & Billing, Subscription, Order and Refunds before cutover. "
            "Finance must be briefed on ledger reconciliation during any write-path "
            "change."
        ),
    },
    {
        "id": "doc-postmortem-2025-07-key-rotation",
        "title": "Postmortem: LegacyPay key rotation outage (2025-07)",
        "source_type": "postmortem",
        "source_uri": "https://wiki.northwind.example/postmortems/2025-07-legacypay-key-rotation",
        "content": (
            "LegacyPay rotated its webhook signing key with no notice, causing 41 "
            "minutes of failed verification. Root cause was a missing vendor "
            "notification channel combined with no key-rotation runbook step. Action "
            "items: add a key-rotation check to the integration runbook and request "
            "advance notice from the vendor."
        ),
    },
    {
        "id": "doc-checkout-owner-handbook",
        "title": "Checkout Team Engineering Handbook",
        "source_type": "handbook",
        "source_uri": "https://wiki.northwind.example/handbooks/checkout",
        "content": (
            "Checkout owns the orchestration between cart, fraud and payment. Any "
            "change to the payment integration requires Checkout review because "
            "Checkout sets the capture deadline and absorbs payment latency. Checkout "
            "maintains the checkout time budget and the connection pool sizing."
        ),
    },
    {
        "id": "doc-ledger-contract",
        "title": "Ledger Sync Contract and SLA",
        "source_type": "spec",
        "source_uri": "https://wiki.northwind.example/specs/ledger-sync-contract",
        "content": (
            "The ledger sync consumes settled payment events and must tolerate "
            "duplicate and out-of-order delivery. Worst-case reconciliation drift is "
            "15 minutes under normal operation. Billing treats any drift beyond one "
            "hour as an incident."
        ),
    },
]

# --------------------------------------------------------------------------
# Relationships
# --------------------------------------------------------------------------
# (source_id, relationship_type, target_id)

OWNERSHIP: list[tuple[str, str, str]] = [
    ("per-amara-osei", "OWNS", "svc-payment-legacy"),
    ("per-diego-ruiz", "OWNS", "svc-payment-v2"),
    ("per-priya-raman", "OWNS", "svc-refunds"),
    ("per-lena-fischer", "OWNS", "svc-checkout"),
    ("per-sofia-ivanova", "OWNS", "svc-invoice"),
    ("per-tom-berg", "OWNS", "svc-ledger"),
    ("per-marcus-oyelaran", "OWNS", "svc-fraud"),
    ("per-james-whitfield", "OWNS", "svc-identity"),
    ("per-noah-adeyemi", "OWNS", "svc-storefront"),
    ("per-noah-adeyemi", "OWNS", "svc-cart"),
    ("per-aya-nakamura", "OWNS", "svc-analytics"),
    ("per-james-whitfield", "OWNS", "svc-webhook"),
    ("per-james-whitfield", "OWNS", "svc-search"),
    ("per-noah-adeyemi", "OWNS", "svc-inventory"),
    ("per-sofia-ivanova", "OWNS", "svc-subscription"),
    ("per-noah-adeyemi", "OWNS", "svc-promo"),
    ("per-james-whitfield", "OWNS", "svc-notification"),
]

# (A) DEPENDS_ON (B)  =>  A breaks if B breaks.
DEPENDENCIES: list[tuple[str, str, str]] = [
    # Tier-1 consumers of the legacy payment integration.
    ("svc-checkout", "DEPENDS_ON", "svc-payment-legacy"),
    ("svc-order", "DEPENDS_ON", "svc-payment-legacy"),
    ("svc-invoice", "DEPENDS_ON", "svc-payment-legacy"),
    ("svc-subscription", "DEPENDS_ON", "svc-payment-legacy"),
    ("svc-refunds", "DEPENDS_ON", "svc-payment-legacy"),
    # The legacy integration's own dependencies.
    ("svc-payment-legacy", "DEPENDS_ON", "svc-ledger"),
    ("svc-payment-legacy", "DEPENDS_ON", "svc-fraud"),
    ("svc-payment-legacy", "DEPENDS_ON", "svc-identity"),
    ("svc-payment-legacy", "DEPENDS_ON", "svc-webhook"),
    # Payment Service B's dependencies. Note: no edge to svc-identity, which is
    # one of the gaps the agent should notice rather than paper over.
    ("svc-payment-v2", "DEPENDS_ON", "svc-ledger"),
    ("svc-payment-v2", "DEPENDS_ON", "svc-fraud"),
    ("svc-payment-v2", "DEPENDS_ON", "svc-webhook"),
    # Second-order consumers, giving genuine multi-hop impact paths.
    ("svc-cart", "DEPENDS_ON", "svc-checkout"),
    ("svc-cart", "DEPENDS_ON", "svc-inventory"),
    ("svc-cart", "DEPENDS_ON", "svc-search"),
    ("svc-storefront", "DEPENDS_ON", "svc-cart"),
    ("svc-storefront", "DEPENDS_ON", "svc-search"),
    ("svc-promo", "DEPENDS_ON", "svc-cart"),
    ("svc-search", "DEPENDS_ON", "svc-inventory"),
    ("svc-notification", "DEPENDS_ON", "svc-identity"),
    ("svc-webhook", "DEPENDS_ON", "svc-notification"),
    ("svc-webhook", "DEPENDS_ON", "svc-identity"),
    ("svc-fraud", "DEPENDS_ON", "svc-analytics"),
    ("svc-analytics", "DEPENDS_ON", "svc-identity"),
    ("svc-subscription", "DEPENDS_ON", "svc-invoice"),
    ("svc-refunds", "DEPENDS_ON", "svc-ledger"),
    ("svc-ledger", "DEPENDS_ON", "svc-identity"),
    ("svc-search", "DEPENDS_ON", "svc-identity"),
    ("svc-inventory", "DEPENDS_ON", "svc-identity"),
    ("svc-checkout", "DEPENDS_ON", "svc-fraud"),
    ("svc-checkout", "DEPENDS_ON", "svc-identity"),
    ("svc-checkout", "DEPENDS_ON", "svc-inventory"),
    ("svc-order", "DEPENDS_ON", "svc-inventory"),
    ("svc-order", "DEPENDS_ON", "svc-webhook"),
    ("svc-invoice", "DEPENDS_ON", "svc-ledger"),
]

PROJECT_USAGE: list[tuple[str, str, str]] = [
    ("proj-payments-modernization", "USES", "svc-payment-legacy"),
    ("proj-payments-modernization", "USES", "svc-payment-v2"),
    ("proj-payments-modernization", "USES", "svc-ledger"),
    ("proj-payments-modernization", "USES", "svc-fraud"),
    ("proj-checkout-v3", "USES", "svc-checkout"),
    ("proj-checkout-v3", "USES", "svc-cart"),
    ("proj-fraud-gateway", "USES", "svc-fraud"),
    ("proj-fraud-gateway", "USES", "svc-analytics"),
    ("proj-fraud-gateway", "USES", "svc-checkout"),
    ("proj-ledger-realtime", "USES", "svc-ledger"),
    ("proj-ledger-realtime", "USES", "svc-payment-legacy"),
    ("proj-webhook-hardening", "USES", "svc-webhook"),
    ("proj-webhook-hardening", "USES", "svc-notification"),
]

PROJECT_WORK: list[tuple[str, str, str]] = [
    ("per-amara-osei", "WORKED_ON", "proj-payments-modernization"),
    ("per-diego-ruiz", "WORKED_ON", "proj-payments-modernization"),
    ("per-priya-raman", "WORKED_ON", "proj-payments-modernization"),
    ("per-priya-raman", "WORKED_ON", "proj-checkout-v3"),
    ("per-lena-fischer", "WORKED_ON", "proj-checkout-v3"),
    ("per-lena-fischer", "WORKED_ON", "proj-payments-modernization"),
    ("per-marcus-oyelaran", "WORKED_ON", "proj-fraud-gateway"),
    ("per-marcus-oyelaran", "WORKED_ON", "proj-payments-modernization"),
    ("per-tom-berg", "WORKED_ON", "proj-ledger-realtime"),
    ("per-tom-berg", "WORKED_ON", "proj-webhook-hardening"),
    ("per-james-whitfield", "WORKED_ON", "proj-webhook-hardening"),
    ("per-james-whitfield", "WORKED_ON", "proj-fraud-gateway"),
    ("per-aya-nakamura", "WORKED_ON", "proj-fraud-gateway"),
    ("per-noah-adeyemi", "WORKED_ON", "proj-checkout-v3"),
    ("per-sofia-ivanova", "WORKED_ON", "proj-ledger-realtime"),
    ("per-sofia-ivanova", "WORKED_ON", "proj-checkout-v3"),
]

INCIDENT_AFFECTED: list[tuple[str, str, str]] = [
    ("inc-2025-07-legacypay-key-rotation", "AFFECTED", "svc-checkout"),
    ("inc-2025-07-legacypay-key-rotation", "AFFECTED", "svc-webhook"),
    ("inc-2025-07-legacypay-key-rotation", "AFFECTED", "svc-payment-legacy"),
    ("inc-2024-11-ledger-drift", "AFFECTED", "svc-invoice"),
    ("inc-2024-11-ledger-drift", "AFFECTED", "svc-ledger"),
    ("inc-2025-03-fraud-timeout", "AFFECTED", "svc-checkout"),
    ("inc-2025-03-fraud-timeout", "AFFECTED", "svc-fraud"),
    ("inc-2025-09-checkout-degradation", "AFFECTED", "svc-checkout"),
    ("inc-2025-09-checkout-degradation", "AFFECTED", "svc-cart"),
    ("inc-2026-02-payflow-sandbox-idempotency", "AFFECTED", "svc-payment-v2"),
    ("inc-2026-02-payflow-sandbox-idempotency", "AFFECTED", "svc-checkout"),
    ("inc-2026-04-webhook-latency", "AFFECTED", "svc-webhook"),
]

# CAUSED_BY is asserted only where the source material supports it.
# inc-2026-04-webhook-latency is intentionally absent from this list.
INCIDENT_CAUSE: list[tuple[str, str, str]] = [
    ("inc-2025-07-legacypay-key-rotation", "CAUSED_BY", "svc-payment-legacy"),
    ("inc-2024-11-ledger-drift", "CAUSED_BY", "svc-ledger"),
    ("inc-2025-03-fraud-timeout", "CAUSED_BY", "svc-fraud"),
    ("inc-2025-09-checkout-degradation", "CAUSED_BY", "svc-checkout"),
    ("inc-2026-02-payflow-sandbox-idempotency", "CAUSED_BY", "svc-payment-v2"),
]

INCIDENT_RESOLVER: list[tuple[str, str, str]] = [
    ("per-priya-raman", "RESOLVED", "inc-2025-07-legacypay-key-rotation"),
    ("per-tom-berg", "RESOLVED", "inc-2024-11-ledger-drift"),
    ("per-marcus-oyelaran", "RESOLVED", "inc-2025-03-fraud-timeout"),
    ("per-lena-fischer", "RESOLVED", "inc-2025-09-checkout-degradation"),
    ("per-amara-osei", "RESOLVED", "inc-2026-02-payflow-sandbox-idempotency"),
    # No resolver recorded for inc-2026-04-webhook-latency.
]

DECISION_AFFECTS: list[tuple[str, str, str]] = [
    ("dec-2023-06-legacypay-adoption", "AFFECTS", "svc-payment-legacy"),
    ("dec-2025-08-payments-modernization", "AFFECTS", "svc-payment-legacy"),
    ("dec-2025-08-payments-modernization", "AFFECTS", "svc-payment-v2"),
    ("dec-2024-02-retain-batch-ledger-sync", "AFFECTS", "svc-ledger"),
    ("dec-2024-02-retain-batch-ledger-sync", "AFFECTS", "svc-invoice"),
    ("dec-2025-05-unified-fraud-gateway", "AFFECTS", "svc-fraud"),
    ("dec-2025-05-unified-fraud-gateway", "AFFECTS", "svc-payment-legacy"),
    ("dec-2025-05-unified-fraud-gateway", "AFFECTS", "svc-checkout"),
    ("dec-2026-01-dual-write-migration", "AFFECTS", "svc-payment-legacy"),
    ("dec-2026-01-dual-write-migration", "AFFECTS", "svc-payment-v2"),
]

DECISION_SUPERSEDES: list[tuple[str, str, str]] = [
    ("dec-2025-08-payments-modernization", "SUPERSEDES", "dec-2023-06-legacypay-adoption"),
]

DOCUMENT_DESCRIBES: list[tuple[str, str, str]] = [
    ("doc-legacypay-integration-runbook", "DESCRIBES", "svc-payment-legacy"),
    ("doc-payflow-gap-analysis", "DESCRIBES", "svc-payment-v2"),
    ("doc-checkout-owner-handbook", "DESCRIBES", "svc-checkout"),
    ("doc-ledger-contract", "DESCRIBES", "svc-ledger"),
    ("doc-migration-runbook-draft", "DESCRIBES", "svc-payment-v2"),
    ("doc-migration-runbook-draft", "DESCRIBES", "svc-payment-legacy"),
]

DOCUMENT_SUPPORTS: list[tuple[str, str, str]] = [
    ("doc-adr-0007-legacy-adoption", "SUPPORTS", "dec-2023-06-legacypay-adoption"),
    ("doc-adr-0021-payments-modernization", "SUPPORTS", "dec-2025-08-payments-modernization"),
    ("doc-postmortem-2025-07-key-rotation", "SUPPORTS", "inc-2025-07-legacypay-key-rotation"),
    ("doc-ledger-contract", "SUPPORTS", "dec-2024-02-retain-batch-ledger-sync"),
]


def all_relationships() -> list[tuple[str, str, str]]:
    """Every relationship triple in the dataset, for validation and seeding."""
    return (
        OWNERSHIP
        + DEPENDENCIES
        + PROJECT_USAGE
        + PROJECT_WORK
        + INCIDENT_AFFECTED
        + INCIDENT_CAUSE
        + INCIDENT_RESOLVER
        + DECISION_AFFECTS
        + DECISION_SUPERSEDES
        + DOCUMENT_DESCRIBES
        + DOCUMENT_SUPPORTS
    )


def all_node_ids() -> set[str]:
    """Every entity id defined by the dataset."""
    ids: set[str] = set()
    for collection in (PEOPLE, SERVICES, PROJECTS, INCIDENTS, DECISIONS, DOCUMENTS):
        ids.update(item["id"] for item in collection)
    return ids


def seed_summary() -> dict[str, int]:
    """Counts used by the seeder, tests, and the API overview endpoint."""
    return {
        "people": len(PEOPLE),
        "services": len(SERVICES),
        "projects": len(PROJECTS),
        "incidents": len(INCIDENTS),
        "decisions": len(DECISIONS),
        "documents": len(DOCUMENTS),
        "relationships": len(all_relationships()),
    }