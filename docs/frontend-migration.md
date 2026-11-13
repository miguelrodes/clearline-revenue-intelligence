# Frontend migration — implementation and verification

Next.js replaces Streamlit for the final demo. React/TypeScript, Tailwind, TanStack Table,
Recharts and Lucide supply the interface; FastAPI is a local HTTP adapter. The existing
Python calculations, agents, Store, SQLite schema and worker were not rewritten.
Streamlit remains an available fallback. No deployment or push is part of this change.

## Product navigation

- **Overview:** saved-scan KPIs, monthly purchasing trends, signal distribution, pending
  emails and recent actual jobs. Each KPI links to underlying records. The historical
  revenue KPI opens a source ledger including distributor sell-in counted once.
- **Opportunities:** search and sortable columns, signal/stage/evidence filters. Default
  ranking puts unheld cases first, then historical decline. Multiple signals stay on one row.
- **Account Intelligence:** purchasing and product evidence, CRM, uncertainty, AI assessment,
  outreach and follow-ups, persistent action history. Real prospects have sourced public
  research instead of fictional purchasing charts.
- **Action Center:** assessment requests, saved-draft approvals, due work and exceptions.
- **Agent Activity:** actual job status, timestamps, errors, retry/cancel, worker heartbeat,
  pause/resume, daily scan settings, commercial outcomes and execution events.
- **Real-world prospects:** a separate entry point for Pennsylvania and Massachusetts DOC.

## Execution contracts

The UI never calls a model or sends email directly. API endpoints enqueue existing worker
jobs or call existing Store methods. Read endpoints do not alter sales records. Requests
are uncached; views refresh every five seconds. Errors remain visible.

Draft changes create a new version. Approval submits the exact saved recipient, subject,
body and version; unsaved changes disable approval. Backend guards reject stale versions,
changed evidence and held accounts. The worker rechecks the saved approval before recording
one simulated delivery, then schedules the existing follow-up. A manually recorded outcome
stops automatic follow-ups. No real transport exists.

A scan defaults to zero new AI assessments. Explicit user actions can request up to three
assessments. The daily-scan control uses zero automatic AI assessments, 90-day inactivity
and 25% decline thresholds. An assessment/reassessment and retry require confirmation.
Paused/offline workers do not execute new tasks. No new model calls were needed for this
frontend migration; prior saved live executions supply the demonstration evidence.

The browser uses a same-origin Next.js proxy. FastAPI restricts Host and mutation Origin
and requires a client header. This is a localhost safeguard, not production authentication.

## Financial integrity

All financial processing stays in Python. Portfolio totals come from the persisted scan;
monthly charts and the source ledger use the original CSV snapshot verified against its
saved hashes. Account charts reuse persisted source-row identities rather than rematching.
Tests cover signed credit memos, open orders, undated rows and November 1 exclusions.
The portfolio monthly/ledger net values and physical-test totals reconcile exactly to the
saved scan. Distributor sell-in is never added again at agency level. Candidate declines
need not equal company-wide change. Historical decline is not a revenue forecast.

## Verification

- 53 Python tests pass, including seven API tests over isolated temporary databases.
- Six frontend workflow tests pass. TypeScript checks and the production build pass.
- API integration covers edit → exact-version approval → worker simulated delivery →
  persisted follow-up → manual reply cancelling follow-up → API restart.
- Additional API tests cover read-only behavior, stale evidence and holds, origin checks,
  request deduplication, explicit reassessment, real-prospect segregation and monthly/ledger
  reconciliation. Frontend tests cover dirty edits, confirmation, error visibility,
  delivered-draft controls, KPI filters and search/stage filtering.
- The three existing cases are reviewed through the running HTTP API and Next.js interface:
  Lone Tree simulated outreach/follow-up; Cedar County pending draft; Pennsylvania DOC
  sourced research, channel recommendation and pending draft. Pending drafts remain pending.
- The pre-migration SQLite backup is kept locally under ignored runtime/. Sales records
  are compared against it after verification; worker heartbeat changes are expected.

## What remains unverified or intentionally limited

Public evidence does not establish buying intent, current vendor status or procurement
eligibility. The UI preserves those uncertainties. This migration does not rerun paid AI
research, send real email, verify live replies, or implement later roadmap phases.
Manual outcomes are demonstration inputs, not achieved sales. The original research and
model executions remain available in history. Desktop-first tables scroll horizontally on
small screens; the sidebar collapses to a menu. This application is local-only and needs
three running processes (frontend, API, worker). Keep Streamlit as fallback through rehearsal.

## Launch and review

See the repository README for fresh-install and three-terminal commands. Open
http://127.0.0.1:3000/ with the API on port 8000 and the existing worker running.
Review Overview → inactive/partial-decline KPI → account → AI assessment → outreach.
Use Cedar County to review a pending approval; Lone Tree shows a completed simulated action.
Real-world prospects → Pennsylvania DOC shows the separate evidence and qualification loop.
Approval and outcome mutations are not required to inspect these saved cases.
