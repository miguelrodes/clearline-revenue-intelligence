> Historical November 12 implementation. The current engine, evaluated results, 24-run worker and revised approval behavior are documented in [the November 13 overhaul](agentic-overhaul.md). Template-based preparation and blanket operational holds described below have been superseded.

> Latest update: see [operational briefing and parallel execution](operational-briefing.md) for the compact AI briefing and the measured 15-investigation worker. The earlier benchmark below is retained as history.

# Agentic portfolio and campaign implementation

Implemented locally on November 12, 2026. Financial comparisons remain January–October
2025 versus January–October 2026, with a November 1, 2026 business cutoff. No real email
transport, cloud deployment, new queue infrastructure, or GitHub push was added.

## What changed

- A full scan includes named order-customer groups, unresolved identity groups, distributor
  bill-to buyers and CRM-only accounts. Public-agency records without a customer connection
  remain prospect records, not presumed existing customers. These are account records, not
  a claim that every group is a verified distinct institution.
- Every account receives a saved evidence-backed assessment: pursue, hold, reject or no
  action. Stable accounts do not receive unnecessary sales messages. Held accounts get
  verification recommendations; the agent cannot clear an evidence hold.
- Evidence investigation, commercial strategy and personalized preparation run in one
  bounded typed agent workflow. Separate agents were not added for handoffs that would only
  repeat context and consume tokens. The executive brief uses a separate small summarization
  call; real-prospect research and qualification retain their existing specialized agents.
- High-value accounts (at least $50,000 historical decline) and complex/held cases use the
  configured high reasoning effort. Routine cases use configurable medium reasoning.
- A campaign selects filtered accounts or the top 15 eligible accounts by historical decline,
  excludes stopped/held/already-contacted accounts, reuses saved current assessments, selects
  one of seven templates and prepares versioned emails. This is transparent financial
  prioritization with eligibility checks, not an invented probability score. Natural-language
  campaign interpretation is not implemented; structured filters provide the working path.
- Campaign review shows every proposed message, strategy, exclusion, associated historical
  decline, simulated deliveries, follow-ups and outcomes. Edit exceptions through account
  outreach. After preparation finishes, bulk approval requires a separate confirmation and
  binds each exact saved version. A stale/missing/changed member aborts the whole transaction.
- Missing verified contacts do not become invented recipients. The fictional campaign flow
  requires an explicit simulated-recipient choice; all recipient addresses are placeholders.
  This is not a verified-contact resolver or an authorized real outreach service.
- Action Center collects campaign approvals and concrete evidence/contact recommendations.
  Accepting a verification task records a decision and note without clearing holds. Defer or
  reject stops pending outreach. Deferred work remains visible through Account Intelligence;
  there is no automatic reopening or invented follow-up date.
- Overview has a saved AI Revenue Brief, automatic change detection with a 60-second debounce,
  a timestamp and manual regeneration. Brief jobs summarize a snapshot, so changes arriving
  during generation appear in the next refresh. Its source snapshot is retained for audit.

## Financial rules

The source-ledger net comparison is unchanged: signed invoices/credits, excluding open and
undated orders from comparable periods. Physical tests exclude training sessions. Positive
historical decreases are not forecasts or recoverable revenue. Segment rows show counts,
associated dollars, comparable percentage change, analyzed/actionable/awaiting-action counts.
Partial decline excludes the inactivity segment. Categories can still overlap: SKU decline
uses affected-product revenue and must not be added to account-level categories.

Distributor buyer records are inspected separately and have no recovery signal category;
their sales already occur in company totals and can also appear in named end-customer views.
Never sum distributor and institution histories as additional revenue. Unresolved aliases
are held; absence of attributed purchases does not establish inactivity or net-new status.

## Throughput audit and architecture

The old worker ran one job to completion before claiming another. Model latency therefore
blocked independent accounts, and the scan's default one-account/maximum-three-account limit
left the rest unassessed. At audit time there was no stuck investigation backlog or evidence
of provider rate limiting: the three queued jobs were future follow-ups. Three earlier saved
recovery executions averaged 26.3 seconds each.

The replacement remains one Python process with `asyncio` tasks and asynchronous Agents SDK
calls. It starts six independent investigations. The maximum is configurable; the current
local ceiling is twelve after the benchmark and observed provider headers justified it.
Capacity increases by one after sustained successful completions when observed throughput
has not fallen and token/request headroom is sufficient. A 429 halves capacity and introduces
a shared cooldown. These are runtime observations, not guaranteed account-wide entitlements.

| Matched six-account real API benchmark | Sequential scheduler | Six concurrent |
| --- | ---: | ---: |
| Completed recommendations | 6 | 6 |
| Wall time | 99.97 seconds | 24.44 seconds |
| Recommendations/minute | 3.60 | 14.73 |
| Returned model requests | 15 | 15 |
| Input tokens | 23,400 | 23,351 |
| Output tokens | 4,195 | 4,374 |
| Estimated standard token cost | $0.0658 | $0.0675 |

Throughput improved 4.09×. Both benchmark arms use the same accounts, analyst, model and
reasoning policy to isolate scheduling; this is not a controlled comparison of old versus
new prompts. Six cases are a small sample, and model latency varies. The provider returned
limits of 5,000 requests and 1,000,000 tokens in its rate-limit headers, with substantial
remaining headroom. The worker relies on returned headers and backoff, not hardcoded limits.

## Persistence and failure behavior

- SQLite WAL, short `BEGIN IMMEDIATE` writes, one exclusive worker lock, atomic job claims.
  No network request runs inside a database transaction.
- Independent accounts execute concurrently; the same account is serialized. Scans are
  exclusive. Approved deliveries, briefs, follow-ups and explicit campaign preparation take
  priority over portfolio investigations without bypassing their safety checks.
- Batch membership and job creation commit atomically. An unchanged evidence hash reuses the
  saved assessment. Interrupted jobs resume under the next worker lock; incomplete model
  requests can repeat, but draft completion and outbox actions are deduplicated.
- SDK automatic retries are disabled so one layer owns retry behavior. Connection/timeouts,
  HTTP 408/409/429 and 5xx retry with jitter, exponential delay and provider retry headers,
  at most five attempts by default. Auth/quota failures block; invalid model results fail
  visibly. Errors do not silently turn into simulated AI output.
- Every action checks current account eligibility and draft approval again at execution.
  Editing creates a new version; stale approval cannot authorize it. Rejections, opt-outs
  and recorded outcomes prevent further outreach. A follow-up requires another saved draft
  and human approval; missing recorded replies are not interpreted as confirmed silence.
- The database was backed up before the migration. Original events, drafts, approvals,
  outbox and the Pennsylvania DOC sources remain preserved.

## Observability and limits

Agent Activity/Action Center show active, queued, completed and failed/blocked investigations,
batch coverage and cache reuse, average processing time, completed recommendations per minute
in the last five minutes, model requests, input/output tokens and estimated API cost. Safe
provider headers, retry events, decision evidence, chosen strategies and attempts persist.
Credentials and request bodies are not logged by the telemetry hook.

Estimates use returned token usage and the published standard price schedule checked on
November 12, 2026: [OpenAI pricing](https://developers.openai.com/api/docs/pricing).
Unknown tool fees, unpriced legacy records, nonstandard tiers and interrupted requests with no
usage response are excluded; estimates are not billing totals. Runtime rate controls follow
[OpenAI rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits).

## Rehearsal path

1. Open Overview: read the persisted Revenue Brief and drill into a financial segment.
2. Open Account Intelligence to inspect the full assessed universe, including no-action and
   verification records. Opportunities shows accounts with meaningful financial signals.
3. In Opportunities, filter or select the top 15 eligible accounts. Prepare a named campaign
   and explicitly select simulated inboxes for the fictional records.
4. In Campaigns, inspect summaries and expand messages; edit any exception. After preparation
   finishes, approve the complete reviewed set. Each action remains individually version-locked.
5. Watch the simulated outbox and scheduled follow-ups. Record a clearly labeled demo outcome
   to stop further follow-ups. No actual customer response or achieved revenue is implied.
6. In Agent Activity, show batch completion, usage, retries and the concurrency ceiling. Scan
   again to demonstrate cache reuse without paying to reassess unchanged evidence.

## Validation

Automated coverage includes six concurrent independent jobs, same-account serialization,
full customer-universe coverage, financial reconciliation, cache reuse, cancellation/restart,
stale evidence, stale bulk snapshots, all-or-none approval, deferral, fifteen simulated sends,
follow-ups, opt-out, no duplicate actions and original prospect workflows. UI tests cover
individual and bulk approvals, immutable review snapshots, pending-preparation locks, error
reporting, editing and financial drill-down. Production TypeScript build passes.

## Completed live run — November 12, 2026

- **486/486 current assessments:** 401 named order-customer groups, 69 unresolved order-name
  groups, 13 CRM-only records and three distributor buyers. All 220 signal-bearing records
  are assessed. These counts do not assert 486 verified institutions.
- **53 pursue, 392 hold, 41 no action.** Of the 53 pursue results, three already have earlier
  simulated outreach, fifteen now have versioned campaign drafts awaiting human approval,
  and thirty-five need contact verification or an explicit fictional simulator campaign choice.
- Holds include distributor-channel evidence (160 records), identity review (157), possible
  missing-state aliases (136), ambiguity (75), open orders (72), undated history (40), missing
  purchase history (13), and multiple shipping cities (2). These reasons overlap.
- **Priority recovery — 15 accounts:** $161,197 associated historical decline; eight inactive,
  three contact-change, three reduced-volume and one channel-clarification strategies. Every
  draft is inspectable and editable. One internal-CRM reference was corrected through a new
  saved version; no live campaign approval or send was performed.
- An isolated copy of the real persisted results passed fifteen individual version-locked
  approvals, fifteen simulated deliveries and fifteen follow-ups; a synthetic reply cancelled
  its follow-up. Restart persistence and duplicate-approval blocking passed. This acceptance
  fixture did not authorize the user's live campaign or add an actual customer response.
- A repeated full portfolio batch reused all **486 assessments with zero new analysis jobs**.
- Eight transient API connection failures were retried successfully. No rate-limit error or
  unresolved failed/config-blocked job remained. The live run reached twelve concurrent
  investigations; the final worker restarts at six and may grow to the configured ceiling.
- At 05:45:51 UTC, returned live telemetry totaled 1,147 model requests, 1,715,726 input tokens
  and 443,433 output tokens; priced live usage was $6.0819. The matched benchmark added
  $0.1333: approximately **$6.22 known estimated token cost**. Eight legacy usage records
  remain unpriced; interrupted requests can have unreported cost. This is not a billing total.
- **68 backend tests, nine frontend tests and a successful production build.** Browser checks
  verified selection of fifteen accounts, campaign preparation, individual message inspection,
  state-specific identity labels, approval preview/cancellation, overview figures and brief.
- Pre-existing four drafts, three approvals, three simulated outbox entries, one prospect
  research bundle and five sources remain unchanged. All company financial/volume totals,
  undated-line treatment and retained duplicate counts match the pre-change backup.

Acceptance details remain local in ignored runtime/: `agentic-overhaul-report.json`,
`campaign-acceptance.json`, `overhaul-preservation.json` and `concurrency-benchmark.json`.
The main database contains no new approvals or simulated sends from this implementation.

## Remaining limitations

Real contact verification, distributor sell-through, ambiguous identities and order-status
resolution require evidence unavailable in the supplied files. The application records and
routes those tasks; it cannot manufacture their answers. No real sales outcome is established.
Campaign instructions use filters, select-all and top-fifteen controls; natural-language
instruction parsing remains optional future work. Local schedules require the worker and an
awake computer. No later product phase, real email integration, production authentication,
MCP adapter, cloud deployment or GitHub push was implemented here.


### Human-guided email revisions

Grouped outreach review supports optional instructions for the selected saved drafts. `/api/work/{group_id}/revise` queues `revise_draft` jobs on the existing worker. Each call validates exact draft snapshots, deduplicates repeat submissions, and persists guidance in job payloads and audit events. Agents use saved account evidence and the current draft, with no sending tools. They preserve recipients and return a subject, body and review note; unspecified discounts remain a pricing discussion rather than invented terms.

New versions remain awaiting approval. Approval is blocked while a selected account has a queued/running revision. Newer edits, changed evidence, stopped accounts or rejected drafts invalidate an in-flight result. Failed revisions retain the previous draft and can be retried through Agent Activity. Completed writes are idempotent. The UI displays progress and revision notes and keeps exact-version approval and autosave behavior.

Validation: backend revision/HTTP/MCP/workbench checks and frontend selection/autosave/approval tests pass. A real model run on an isolated demo database copy produced an evidence-based replenishment/quote revision, retained the recipient, required fresh approval, and added no outbox entries (one request, estimated $0.004022). Existing demo drafts were not revised during verification.
