# Repeatable customer conversation demo

Implemented locally on November 12, 2026. The existing Next.js, FastAPI, Python Agents SDK, SQLite, worker and approval flow are reused. No real email provider is configured or implemented.

## Starting state and reset

The registered disposable database is `runtime/demo/session.sqlite3`; its separate baseline is `runtime/demo/baseline.sqlite3`. The original `runtime/clearline.sqlite3` and all four supplied CSVs remain unchanged. Tests verified their file hashes.

The reset restores **51 pending recovery emails**, including **ID DOC – Lone Tree**, 2 earlier recovery sends with follow-up examples, 392 assessed verification records, and 41 no-action records. All 486 recovery records retain their saved assessments. The separate real-prospect records remain separate. Lone Tree starts with its saved version 1, no approvals or conversation messages in the disposable copy, and its existing financial evidence. Juniper Hills retains its open-order hold.

Run from a terminal:

```bash
cd /Users/miguelrodes/Code/clearline-revenue-intelligence
.venv/bin/python scripts/reset_demo.py
.venv/bin/python -m clearline.demo serve
```

Leave the second command running and refresh http://127.0.0.1:3000/. The frontend runs separately; if needed, start it in another terminal with `npm --prefix frontend run start` from the same folder. `python3 scripts/reset_demo.py` also works: the wrapper selects the repository virtual environment.

Reset verifies the registered paths and baseline checksum, coordinates shutdown of the registered API and worker, archives the old rehearsal under `runtime/demo/history/`, and restores the known baseline. Independently launched processes holding the demo lease must be stopped first. Follow-up dates shift relative to the reset date. Financial assessments and compatible briefing wording are reused; no portfolio-wide AI analysis is required. Each rehearsal remains available in the archives. Do not use `capture` during a rehearsal: it deliberately replaces the baseline.

## Five-minute demonstration

1. Open http://127.0.0.1:3000/accounts/c966fd651cca1e9020fa or search for **Lone Tree**. Its comparable January–October purchasing declined by $50,225. The saved recommendation first checks the contact and purchasing route; it does not assume the whole decline is recoverable.
2. In **Next action**, review version 1 and choose **Approve simulated send**, then **Confirm**. The worker saves the approved email into the simulated conversation.
3. In **Customer conversation**, expand **Demo control · simulate a customer reply**. Select the outbound message. Choose an optional example or write your own fictional reply. The examples only fill editable text; they do not supply an AI classification.
4. Choose **Inject reply & run AI**. A real OpenAI call interprets that text. The panel displays progress, the exact incoming text, extracted facts, uncertainties, result and commercial next step. The old unanswered-email reminder is canceled immediately.
5. For a reorder, training, or contact-change request, inspect the response under **Next action**. It remains unsent until you separately approve and confirm that exact saved version. The second simulated outbound message links to the inbound reply and completes its associated task.
6. For distributor purchasing, the agent records a channel question, pauses direct outreach and creates an internal next-step task. For rejection or opt-out, outreach stops and no response draft is created. The Action Center surfaces pending customer-request tasks and prepared reply approvals.
7. Run reset again. Lone Tree returns to version 1 awaiting approval. New replies, response drafts, approvals and simulated deliveries from the rehearsal are absent from the active database, but retained in the rehearsal archive.

The browser walkthrough tested the original email, fictional night-shift training reply, real agent execution, a separately approved training response, and the linked three-message conversation. The restored app is ready to repeat this sequence.

## Behavior and safeguards

- `ReplyDecision` is a strict structured output, covering intent, customer statements, requested products/quantities/units, reported contact, channel, uncertainties, commercial status, next action, and optional draft. Exact supporting quotations, supplied SKUs, stated contact fields, intent/status consistency and no-price constraints are validated before changes commit. This is schema/evidence validation, not a guarantee of semantic correctness; humans review outbound prose.
- Requests are not orders. A quote request does not record revenue, reserve stock, set a price, or promise fulfillment. Unknown quantities and units remain unknown.
- Reported contact details are saved against the account with source message, simulated provenance and `verified=false`; they do not replace historical source records or establish real-world verification. All automatic draft recipients remain simulator addresses.
- Messages share a stable conversation, have timestamps and explicit parent-message links, and retain applicable campaign membership. Inbound external IDs and content fingerprints prevent repeated processing. Reusing an ID for different content is rejected.
- Receiving a reply cancels obsolete reminders and pending sends/preparations, invalidates unsent drafts and supersedes old pending tasks. Same-account jobs remain serialized. An older ordinary result cannot replace a newer reply; a late opt-out still suppresses outreach.
- A subsequent inbound reply or portfolio reassessment cannot automatically remove a stop-contact or distributor-review restriction. Manual commercial outcomes also stop inappropriate work. Existing source-data holds remain enforced.
- Every outbound response uses the same exact-version approval and atomic delivery transaction as initial outreach. Duplicate sends remain blocked. No real network email transport exists.
- The `MessageProvider` contract covers approved delivery, ingestion and conversation retrieval. Message records carry account/campaign association, parent linkage and status. Only `SimulatedProvider` is implemented; Gmail, Microsoft Graph, OAuth, webhooks and production deployment are deferred.

## Verification

- **112 backend tests and 32 frontend tests passed.** Production build and TypeScript checks passed.
- Coverage includes all requested response types, structured output rejection before mutation, exact fresh approvals, thread linkage, duplicate/conflicting inbound IDs, contact persistence, distributor restriction persistence, stale-result races, opt-out suppression, no real delivery, and workflow → reset → workflow replay.
- Real AI passed quote/reorder, training, changed purchasing contact, distributor purchasing, not interested, and opt-out. Reorder was repeated after reset. The browser also completed a training conversation using the actual background worker.
- **9 real reply analyses** plus **3 automatic briefing calls** were recorded for this acceptance run: **12 model calls**, estimated **$0.103488** from saved provider usage and the application's existing pricing table. This is an estimate, not an invoice. No research tools were required.
- The initial quote test expected the exact intent `reorder`; the model correctly returned `pricing` with `reorder_interest` and 20 packs. The test expectation was widened to accept that valid distinction. No keyword classification was added.
- Browser testing caught and fixed rendering of older structured channel evidence and a response link that opened an unwanted account overlay. Regression tests cover both. Final checks have no outstanding failures.
- Acceptance details, model output, usage and preservation audit are saved in ignored local `runtime/demo/validation/`. Rehearsal database snapshots remain under `runtime/demo/history/`.

## Files changed for this milestone

- `src/clearline/conversations.py`: conversation schema, migration, deduplicated ingestion, validated atomic reply effects, reported account context and commercial tasks.
- `src/clearline/transport.py`: provider contract and simulator implementation.
- `src/clearline/reply_agent.py`: bounded genuine AI interpretation and output validation.
- `src/clearline/store.py`, `worker.py`, `reporting.py`, `workbench.py`, `api.py`: integrate conversation persistence, approvals, restrictions, worker execution, prepared groups and local API endpoints.
- `src/clearline/demo.py`, `scripts/reset_demo.py`: isolated baseline and simple reset entry point; Lone Tree preparation.
- `frontend/src/components/conversation.tsx`, `sales-surface.tsx`, `detail-views.tsx`, `frontend/src/lib/types.ts`, `frontend/src/app/globals.css`: compact conversation panel, fictional-reply control, current next-step text and assessment compatibility.
- `tests/test_conversations.py`, reply fixtures/regressions, and `frontend/tests/conversation.test.tsx`: automated acceptance and UI regression coverage. Existing reset tests remain passing.
- This guide, `docs/demo-readiness.md`, README and `docs/notion-update-pending.md`: current usage, evidence and limitations.

## Remaining limitations

The app and local worker must be running, with configured OpenAI API access, for new replies to be interpreted. Failed calls remain visible and retryable. No real inbox, live contact verification, distributor-record access, automatic quote/pricing engine, booked sale or verified incremental revenue is demonstrated. Channel/source questions still need genuine information from the relevant team. Opt-ins are not automatically inferred from later messages.

Notion could not be updated: its fetch connector again returned `Unknown tool (notion.fetch)`. The intended update is preserved in `docs/notion-update-pending.md`; reconnecting Notion is the only outstanding external step. No push or deployment was performed.
