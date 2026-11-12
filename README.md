# Clearline Revenue Intelligence

Local Phase 1 customer recovery and one real SwabTek prospecting workflow for the Jola case study.
The supplied Clearline identities and financials are fictional. This application does not
claim they describe real SwabTek customers or achieved sales.

## Run locally

Use Python 3.11 or newer. The UI and worker are separate processes; closing the UI does
not stop a running worker. Keep the computer awake for scheduled execution.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
cp .env.example .env
.venv/bin/clearline init
.venv/bin/clearline scan --analysis-limit 0
.venv/bin/clearline worker
```

In another terminal, from the repository:

```bash
.venv/bin/streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Set `CLEARLINE_DATA_DIR` to the original case-study folder. The four CSVs are read in place;
do not copy them into Git. Runtime data, keys, the outbox, and the SQLite database are ignored.
Synthetic test fixtures are created only in temporary test directories.

## OpenAI setup

1. Sign in to [OpenAI Platform](https://platform.openai.com/), select/create an API project,
   and enable API billing or sufficient API credits.
2. Create a project API key at [API keys](https://platform.openai.com/api-keys).
3. Open the local `.env` file in an editor. Set `OPENAI_API_KEY` there. Never paste it into chat,
   put it on a command line, or commit it. Keep `.env.example` blank.
4. `OPENAI_MODEL` is configurable; the initial default is `gpt-6.1-sol`.
   `OPENAI_REASONING_EFFORT=medium` is also configurable.
5. Run `.venv/bin/clearline verify-api` to list account-visible text models and confirm the
   configured ID. This checks model visibility, not inference permissions or billing; the first
   real recovery run verifies those. Restart the worker after changing `.env`.
6. In the UI, choose an unheld account and click **Ask recovery agent**, or retry its
   `blocked_config` job in **Jobs & activity**. No synthetic AI output is substituted for an error.

The SDK uses the real Responses API with typed outputs and account-evidence tools. Phase 1
does not web-search fictional customer identities. The separate **Real prospects** workflow uses
only public institution/manufacturer evidence, never fictional CSV customer matches. All model/tool calls are bounded and logged;
remote SDK trace uploads are disabled. Token usage is recorded; no invented dollar-cost estimate
is shown. API keys are never logged.

## Workflow and controls

- The scan detects inactivity, overall purchasing decline, and product volume decline.
- Period comparisons use `[year start, as-of)`; purchases on the as-of date suppress stale alerts.
  `CLEARLINE_AS_OF` is the business clock; schedules use actual UTC time.
- Invoice values plus signed credit memos form the net proxy. Open lines are excluded;
  undated rows remain outside time comparisons. Duplicate-looking rows are retained.
- Physical volumes exclude training. Constant old-list values illustrate pack changes,
  not realized revenue, negotiated price, causality, or forecasts.
- Identity, undated history, missing-state aliases, open orders, and known distributor activity
  can block outreach. Unknown downstream customers remain a global caveat even without a hold.
- Every AI decision is evidence-backed and typed; it can pursue, hold or reject. A draft requires
  explicit human approval of its saved version. Edits invalidate approval. The worker rechecks
  approval and current evidence immediately before recording an action.
- Delivery is a **simulated outbox only**. There is no real email transport. A simulated delivery
  schedules at most one follow-up; the follow-up draft needs its own approval. A manually recorded
  reply, qualification, quote, order, loss, opt-out or closure stops follow-ups and is visibly labeled
  as demo input. Quote/order references prevent duplicate recording for that account and outcome type.
- The selected account includes a restoration scenario with an explicit assumption. Optional gross
  margin is also a user-entered assumption: no cost data, verified subsequent revenue, or EBITDA
  improvement is inferred. Demo outcome counts are separate from historical purchasing totals.
- Pause prevents the worker from starting new jobs. Cancel discards the result of an in-flight
  analysis; the provider may still charge for a request already running. Unsaved draft edits cannot
  be approved. The activity view shows worker health, errors, tool events, and returned token usage.
- Failed jobs require explicit retry, avoiding silent token spend. Missing credentials create
  `blocked_config` jobs. Only one worker may own a database. Interrupted jobs are recovered at
  restart; an interrupted model request may be repeated, but outbox actions are deduplicated.

## Scheduling and checks

```bash
.venv/bin/clearline schedule                 # daily, worker must be running
.venv/bin/clearline schedule --seconds 30    # short demo interval
.venv/bin/clearline schedule --seconds 30 --analysis-limit 0  # prove scanning without API spend
.venv/bin/clearline schedule --disable
.venv/bin/clearline status
.venv/bin/python -m pytest -q
```

Manual and scheduled scans use the same queue. A scan automatically queues at most one new
reviewable case by default; the UI supports zero to three. Missed schedule intervals coalesce
into one run. Existing drafts are not regenerated by every scan. Model turns, output tokens,
request timeouts, and follow-up delay are configurable in `.env.example`.

Tests cover financial and matching counterexamples, approval invalidation, duplicate actions,
restart recovery, pause/cancel, replies, missing credentials, and the SDK boundary using a small
test-only response stub. A subprocess test runs a genuinely scheduled scan with zero AI calls.

## Demo sequence and validation

1. Start the worker and UI, then open `http://127.0.0.1:8501`. Run a scan with zero to three new
   agent analyses, or select an existing case and ask the recovery agent.
2. Inspect revenue and physical-volume evidence, identity/channel flags, hypotheses and the
   recommendation. Compare an inactive account with an active account showing reduced purchases.
3. Review the draft. Save any edits first, then approve or reject the exact saved version.
4. Check the simulated outbox and scheduled follow-up. Any new follow-up draft requires separate
   approval. The worker continues independently while the UI is closed.
5. Record an explicitly labeled demo response or commercial outcome to stop the sequence. Use
   Jobs & activity to inspect failures, retry after fixing a cause, or cancel queued work.

Local acceptance on November 11, 2026 verified account-visible `gpt-6.1-sol` with high reasoning,
real evidence-tool execution for inactivity and reduced purchasing, a human-approved simulated
delivery, and a real follow-up draft. Follow-up timing and reply cancellation were tested in an
isolated database copy; the main seven-day schedule was preserved. Local acceptance details are
under ignored `runtime/`, not in Git. Model access may differ for another API project.

Resolved live failures included a configured model-ID typo and incompatible evidence-reference
format; typed references now constrain output. The live follow-up's wording also prompted an
instruction refinement to keep simulation mechanics out of recipient-facing copy. Human review
remains essential. Beyond the single public-prospect slice below, later phases, MCP, production
hosting, and real email delivery remain unimplemented.

The daily scan is off until enabled in Controls or through the CLI. Keep the worker running and
the computer awake; local schedules cannot run while the machine is asleep. After changing `.env`
or backend code, restart the worker. Existing completed analyses are reused, not charged again;
failed jobs require explicit retry. Use a separate database path for disposable demonstration data.

## Real SwabTek prospecting slice

See [scope, sources, assumptions and review instructions](docs/prospecting-slice.md).

```bash
.venv/bin/clearline prospects --research-first
.venv/bin/clearline worker
```

This seeds two curated public leads and queues only Pennsylvania. The worker researches official
sources, persists evidence, then independently qualifies the prospect and drafts an email. Open
**Real prospects → Pennsylvania Department of Corrections** to review the linked claims, proposed
channel and pending draft. Approvals reuse the existing simulated outbox; no real recipient is set.

One research run is limited to six hosted web actions and one model response; qualification uses
at most three model turns and no additional web research. Results survive worker/UI restarts.
The live acceptance included one explicit research retry after an unobserved citation was rejected,
and one qualification retry after an unknown reference was rejected. Source references now use
schema-constrained IDs, and rejected typed output is retained for diagnosis. This validates
execution and safeguards, not product efficacy, buying intent, or sales outcomes.
