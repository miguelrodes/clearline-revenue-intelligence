# Simplified sales interface

Implemented locally on November 12, 2026. This document supersedes the navigation and briefing descriptions in earlier migration/briefing milestones. Next.js, FastAPI, the Python agents, SQLite, and the single concurrent worker remain in place. Nothing was pushed or deployed.

## Review path

1. Open Overview. Its briefing contains at most five ranked operational priorities; each opens its prepared work in a review overlay.
2. Open Action Center for all pending work. Group/filter by action, account, product, priority or status. Recovery campaigns, execution history and automation settings are secondary, expandable tools. Later-phase prospecting is hidden from the Phase 1 interface; its backend and saved research remain intact.
3. Open a ready-email group. Select all or a subset, expand messages, save any edits, then explicitly confirm the selected versions for simulated sending. Unselected drafts remain pending. Opening customer evidence preserves the group and selection.
4. Use global account search or a KPI to inspect accounts/evidence without leaving the current review. Detailed assessments and advanced controls remain available.
5. On Overview, switch Recovery performance to Simulated results. Record a reply or order against a previously contacted customer. A reply stops the previous sequence and queues a real AI response recommendation/draft; every new response or follow-up needs fresh approval.

The existing 15-account saved campaign was already approved before this change. Its simulated deliveries remain in history. Action groups now include all eligible prepared messages regardless of whether someone created a named campaign; their availability depends on current saved work, not hardcoded demo counts.

## What changed

- Exactly two primary navigation destinations, Overview and Action Center, with global account search. Existing direct URLs and functionality remain compatible.
- Deterministic priority ranking uses urgency, readiness, available historical exposure and remaining work. AI writes short grounded descriptions; backend-owned action IDs, counts and destinations are validated. No invented recovery probability or overdue-order claim.
- Briefing refreshes after material changes while the worker is awake. Unchanged state is cached; manual refresh and last successful generation time remain visible. Failed generations do not repeatedly enqueue themselves.
- Counts and revenue use the same four signal categories, including zero. The revenue view retains each segment's existing calculation, and overlapping categories are explicitly non-additive.
- KPI/purchasing overlays show definitions, comparable charts, account/product evidence and source transactions. Existing accounting calculations were not rewritten.
- Work is prepared in action groups, including initial outreach, customer replies and follow-ups. Selected approval validates every saved snapshot under one write transaction before any decision is committed. Exclusions, holds, edits, current evidence, duplicate prevention and delivery checks remain enforced.
- Record problems are four prepared internal requests, not hundreds of isolated sales tasks. Copy/download is not transmission, assignment or resolution. Source corrections and a new scan are still required.
- Refresh portfolio intelligence coordinates the deterministic scan with AI review of new/changed evidence; unchanged assessments are reused. The old scan only recalculated purchasing signals; the old assessment control used the saved scan. Advanced controls remain secondary.
- Simulated orders and signed credits are linked to preceding outreach. The chart counts distinct contacted/responding/purchasing customers and observed net purchases. Verified outcomes and causal incremental recovery remain unavailable; neither is fabricated.
- A bounded reply agent interprets recorded simulated responses, using existing evidence, telemetry, persistence and worker retries. Newer replies and opt-outs invalidate stale results. An existing follow-up draft suppression bug was fixed; follow-ups now produce separately reviewable drafts.

## Validation

- 91 backend tests passed; 25 frontend tests passed; TypeScript and production build passed.
- Coverage includes partial-batch approvals, stale/held drafts, unsaved edits, excluded recipients, response races, follow-up approval, change-driven caching, consistent signal views, outcome provenance and contextual account navigation.
- One real response-agent execution in an isolated database produced a training reply awaiting approval. The unselected customer's email stayed pending. A simulated $200 order minus a $50 credit produced $150 observed simulated net sales, with no verified or incremental claim.
- The isolated response run used one model request and 1,423 reported tokens, estimated at $0.004438. Three live briefing requests after the preservation snapshot used 7,632 tokens, estimated at $0.020960. Combined observed estimate: $0.025398; provider billing is authoritative, and unavailable tool fees are excluded.
- The live preservation audit compared complete row hashes: 3 scans, 488 account records, 20 draft versions, 18 approvals, 18 simulated outbox entries, 0 outcomes, 1 saved campaign/15 memberships, 1 prospect research record and 5 research sources are unchanged. Acceptance approvals/outcomes exist only in the isolated test database.
- Live API health and briefing links were checked. Browser review exposed a Next.js link-event issue; capture-phase contextual navigation and a regression test fixed it.

## Remaining limits and handoff

The live dataset has 35 contact-verification candidates, one prepared real-prospect email retained in backend, hidden from the Phase 1 interface, and 18 upcoming recovery follow-ups, and four overlapping record-check groups covering 174 signal-bearing records. Another 218 held records have no recovery signal and stay outside daily sales work. Counts are a point-in-time snapshot.

Fictional accounts cannot be matched to real contacts by web research. Provide source contacts, or explicitly select simulator inboxes in the contact group to prepare the batch from cached recommendations. That choice neither approves nor sends emails.

There is no real email transport, CRM sync, source-response importer, automatic hold override, verified sales ingestion or incremental-attribution model. All outcomes entered in the current interface are simulated. The daily scan is available but currently not scheduled; change-driven briefing and due-job execution require the running worker and an awake computer.

Notion could be read but not updated: the update/access tools returned Unknown tool; browser sign-in and unavailable native editing prevented the fallback. The exact update is preserved in [notion-update-pending.md](notion-update-pending.md). Existing Notion content was not changed.

Runtime evidence is stored locally in `/tmp/clearline-surface-live-result.json`, `/tmp/clearline-surface-final-audit.json`, and the isolated `/tmp/clearline-surface-acceptance.sqlite3`. Do not upload runtime databases or case-study CSVs.

See [demo readiness](demo-readiness.md) for the superseding prepared baseline, verified counts and reset instructions.
