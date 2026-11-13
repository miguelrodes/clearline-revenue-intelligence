# Phase 1 demo readiness — November 12, 2026

## Current result

The Next.js interface, FastAPI adapter, SQLite store, concurrent Python worker and approval controls remain in place. The visible workspace focuses on customer recovery. Global search also finds the two separately identified real SwabTek prospects; their saved research is read-only in this workspace, without prospect-sourcing or outreach controls.

- All **486 distinct recovery account records** have current persisted AI assessments. The full deterministic scan was rerun; all 486 assessments were reused, with no arbitrary batch cutoff and no public-agency research. Unresolved identity records are included in this count; it does not establish 486 verified institutions.
- Original history: 392 verification cases, 35 contact checks, 41 no-action decisions, 18 customers with prior simulated outreach. No unassessed accounts or failed assessments.
- Disposable demo baseline: **51 pending personalized emails**, grouped into 14 inactivity, 27 reduced-purchasing, 3 product-decline and 7 other justified recovery check-ins. They reuse saved AI prose and explicit simulator inboxes, not invented real contacts. Two saved campaigns remain accessible. Two earlier simulated deliveries and their scheduled follow-ups remain as examples.
- The 392 evidence-verification records are already assessed. Four prepared team requests cover 174 records with current recovery signals; 218 additional records have no current recovery signal and stay out of the primary sales action list. Request memberships overlap.
- Demo dispositions: 51 awaiting approval, 2 outreach/follow-up in progress, 392 requiring verification, 41 no action, 0 unassessed, 0 failed.

## Interface and execution

The opening briefing contains up to five executable groups. Titles describe commercial objectives; short AI descriptions explain the prepared work. Historical financial significance is calculated by Python and is never presented as forecast recovery. Priority uses actual response/due status, readiness, historical decline and evidence-quality discounts for unresolved identity/channel checks. No fulfillment deadlines are invented.

Each opportunity signal opens its own summary, relevant chart and all associated recommendations, including campaign members. Inactivity shows purchase comparisons and last-purchase gaps; partial decline compares customer revenue; SKU deterioration compares qualifying products and physical tests; direct purchase gaps compare the saved direct and identified purchase gaps with distributor evidence. Account- and SKU-level dollar calculations retain their separate definitions and overlap warning.

Signal-specific bulk review and verification exports are restricted to the selected customers. They use existing groups and exact draft hashes, not duplicate campaigns. Editing a selected draft invalidates the prior approval selection. Sending remains simulated; no real email transport exists.

Global search placeholder: **Find a customer, prospect, or account...** Fictional Clearline accounts and real SwabTek prospects are clearly distinguished.

Unchanged account assessments and briefing content do not expire merely because an hour passes. A source refresh queues only changed evidence. Recorded replies trigger response preparation; outcomes stop obsolete follow-ups and change the briefing. Manual refresh remains available. Source corrections/new orders still enter through the existing CSV refresh; there is no live CRM or email ingestion.

## Exact reset procedure

The app now reads the disposable `runtime/demo/session.sqlite3`. The original `runtime/clearline.sqlite3`, CSVs, saved evidence, research and historical approvals remain intact.

From a terminal:

```bash
cd /Users/miguelrodes/Code/clearline-revenue-intelligence
.venv/bin/python scripts/reset_demo.py
.venv/bin/python -m clearline.demo serve
```

Then refresh **http://127.0.0.1:3000/**. Leave the `serve` terminal running. The frontend stays running separately; if it has stopped, use a second terminal in the repository:

```bash
npm --prefix frontend run start
```

`reset` stops only the registered demo supervisor after verifying its process identity, waits for its API and worker to exit, archives the previous rehearsal under `runtime/demo/history/`, validates the baseline checksum, and restores prepared drafts, campaigns and pending approvals. Follow-up dates shift relative to the reset date. Saved AI wording is reused; no portfolio model rerun is needed. The next command starts the same API and worker against the restored copy. Unknown paths, source/database aliases, changed baselines and other active users are rejected. If the API or worker was started independently, stop those demo processes before retrying.

`init` is a one-time setup and refuses to overwrite an existing baseline. `capture` is a developer-only command to deliberately replace the demo baseline after stopping the demo; the previous baseline is archived. Normal rehearsals should use **reset**, not capture.

## Latest conversation verification

See [the complete conversation demo guide](customer-conversation-demo.md) for the implementation, all six real AI scenarios, 112 backend tests, 32 frontend tests, exact reset instructions, API usage and remaining limitations. Lone Tree is the repeatable example.

## Earlier readiness verification (before the conversation extension)

- Full regression: 96 backend tests and 28 frontend tests passed, plus production build and TypeScript checks. Two additional targeted tests for direct-channel evidence and process-identity refusal also passed (98 backend tests total).
- Coverage includes signal account/dollar scope, qualifying SKU reductions, same-campaign action reuse, signal-filtered bulk approvals, exact-version and stale-draft rejection, replies stopping old sequences, no real transport, baseline restoration, refusal while active, source-history preservation and unassessed versus verification dispositions.
- Real AI rehearsal: two selected emails were approved and simulated; Antelope County's simulated training/supplies reply produced a new draft awaiting fresh approval. Reset restored all 50 pending emails and removed the rehearsal outcomes from the active copy while retaining the archived rehearsal.
- Three real model requests (two briefing iterations, one reply): 7,079 input tokens, 1,225 output tokens; estimated **$0.026408** using recorded provider usage and the existing pricing table. No web tools were needed. This is an estimate, not a billing statement.
- The actual registered-service reset command was exercised, then the API and worker were restarted successfully.

## Remaining boundaries

Customer identities, open orders, missing dates, distributor end customers and real purchasing contacts remain unverified where source evidence is missing. They are not silently cleared for demo convenience. Manual outcomes are simulated, not independent proof of incremental sales. Team information requests are prepared but not sent; someone must correct source records before reassessment.

Notion synchronization is blocked: both the page-fetch and documentation-fetch tools returned `Unknown tool`. The current status is saved locally in this document and `docs/notion-update-pending.md`. No GitHub push or deployment was performed.
