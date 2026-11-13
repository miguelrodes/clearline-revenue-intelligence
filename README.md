# Clearline Revenue Intelligence

Local Phase 1 customer recovery app for the Jola case study. Later-phase prospecting code and data remain in the backend and are hidden from the Phase 1 interface.
The supplied Clearline identities and financials are fictional. This application does not
claim they describe real SwabTek customers or achieved sales.

## Current Phase 1 engine

See [the verified agentic overhaul report](docs/agentic-overhaul.md): 486 current assessments, evidence tools and independent QA, 24 concurrent investigations, exact-version simulated approvals, and shared HTTP/MCP execution. The original reset baseline is preserved.

## Run locally — Next.js demo interface

Use Python 3.11+ and Node.js 20.9+. Run all Python commands from this repository.
The frontend, API and worker are separate local processes. Closing a browser does not stop
execution; scheduled work requires the computer to remain awake and the worker to run.
The existing `.env` and database remain in place—do not reinitialize them for this migration.

For a new checkout only:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
cp .env.example .env
# Configure the local .env before continuing.
.venv/bin/clearline init
.venv/bin/clearline scan --analysis-limit 0
```

Start these in separate terminals (only one worker per database):

```bash
# Terminal 1: thin local API
.venv/bin/uvicorn clearline.api:create_app --factory --host 127.0.0.1 --port 8000

# Terminal 2: existing agent and scheduling worker
.venv/bin/clearline worker

# Terminal 3: frontend
cd frontend
npm ci
npm run build
npm run start
```

Open **http://127.0.0.1:3000/**. For frontend development, use `npm run dev` instead of
build/start. Next.js forwards `/api` to the Python API on port 8000. API documentation:
http://127.0.0.1:8000/docs. Bind these processes to loopback only; authentication is out of scope.

Streamlit is deprecated for the final demo but retained as a working fallback:

```bash
.venv/bin/streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Fallback address: http://127.0.0.1:8501/. Both frontends use the same existing database.
Set `CLEARLINE_DATA_DIR` to the original case-study folder. CSVs are read in place;
do not copy them into Git. Runtime data, keys, outbox, SQLite, build output and dependencies
are ignored. Synthetic test fixtures exist only in temporary test directories.

See [the current two-section interface and review path](docs/simplified-control-surface.md) for
implementation, verification and limitations. [Frontend migration](docs/frontend-migration.md)
records the earlier migration milestone.

## OpenAI setup

1. Sign in to [OpenAI Platform](https://platform.openai.com/), select/create an API project,
   and enable API billing or sufficient API credits.
2. Create a project API key at [API keys](https://platform.openai.com/api-keys).
3. Open the local `.env` file in an editor. Set `OPENAI_API_KEY` there. Never paste it into chat,
   put it on a command line, or commit it. Keep `.env.example` blank.
4. `OPENAI_MODEL` is configurable; the initial default is `gpt-6.1-sol`.
   `OPENAI_REASONING_EFFORT=high` is also configurable.
5. Run `.venv/bin/clearline verify-api` to list account-visible text models and confirm the
   configured ID. This checks model visibility, not inference permissions or billing; the first
   real recovery run verifies those. Restart the worker after changing `.env`.
6. In Overview, click **Refresh portfolio intelligence** to scan purchases and review new/changed
   evidence. Retry blocked jobs in **Action Center → Agent activity and automation**.
   No synthetic AI output is substituted for an error.

The SDK uses the real Responses API with typed outputs and account-evidence tools. Phase 1
does not web-search fictional customer identities. The separate **Prospecting Agent** workflow uses
only public institution/manufacturer evidence, never fictional CSV customer matches. All model/tool calls are bounded and logged;
remote SDK trace uploads are disabled. Returned model usage and published standard token prices produce a labeled API cost estimate;
unknown tool fees, legacy unpriced usage and interrupted requests are excluded. API keys are never logged.

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
- Every AI decision is evidence-backed and typed; it can pursue, hold, reject or recommend no action. A draft requires
  explicit human approval of its saved version. Edits invalidate approval. The worker rechecks
  approval and current evidence immediately before recording an action.
- Delivery is a **simulated outbox only**. There is no real email transport. A simulated delivery
  schedules at most one follow-up; the follow-up draft needs its own approval. A manually recorded
  reply, qualification, quote, order, loss, opt-out or closure stops follow-ups and is visibly labeled
  as demo input. Quote/order references prevent duplicate recording for that account and outcome type.
- The Streamlit fallback includes a restoration scenario with an explicit assumption;
  the Next.js interface presents observed historical decline without a recovery forecast. Optional gross
  margin is also a user-entered assumption: no cost data, verified subsequent revenue, or EBITDA
  improvement is inferred. Demo outcome counts are separate from historical purchasing totals.
- Pause prevents the worker from starting new jobs. Cancel discards the result of an in-flight
  analysis; the provider may still charge for a request already running. Unsaved draft edits cannot
  be approved. The activity view shows worker health, errors, tool events, and returned token usage.
- Transient network, rate-limit and server failures retry with jitter and bounded backoff (five attempts by default); permanent failures require explicit retry. Missing credentials create
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
# From frontend/:
npm test
npm run build
```

Manual and scheduled scans use the same queue. By default a scan assesses the entire customer
portfolio, reusing unchanged evidence. The UI also supports a scan without new AI work. Missed schedule intervals coalesce
into one run. Existing drafts are not regenerated by every scan. Model turns, output tokens,
request timeouts, and follow-up delay are configurable in `.env.example`.

Tests cover financial and matching counterexamples, approval invalidation, duplicate actions,
restart recovery, pause/cancel, replies, missing credentials, and the SDK boundary using a small
test-only response stub. A subprocess test runs a genuinely scheduled scan with zero AI calls.

## Demo sequence and validation

1. Start the worker and UI, then open `http://127.0.0.1:3000`. Read the Revenue Brief and commercial segments. Assess the portfolio or run a full recovery scan.
   Select the top 15 eligible opportunities and prepare a campaign with explicit simulated recipients.
2. Inspect revenue and physical-volume evidence, identity/channel flags, hypotheses and the
   recommendation. Compare an inactive account with an active account showing reduced purchases.
3. Open Campaigns. Review the summary, exclusions and templates; expand any message or edit exceptions.
   Approve the completed campaign in bulk; every exact draft version is individually authorized.
4. Check the simulated outbox and scheduled follow-up. Any new follow-up draft requires separate
   approval. The worker continues independently while the UI is closed.
5. Record an explicitly labeled demo response or commercial outcome to stop the sequence. Use
   Activity to inspect failures, retry after fixing a cause, or cancel queued work.

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

The daily scan is off until enabled in Agent Activity or through the CLI. Keep the worker running and
the computer awake; local schedules cannot run while the machine is asleep. After changing `.env`
or backend code, restart the worker. Existing completed analyses are reused, not charged again;
exhausted/permanent failures require explicit retry. Use a separate database path for disposable demonstration data.

## Real SwabTek prospecting slice

See [scope, sources, assumptions and review instructions](docs/prospecting-slice.md).

```bash
.venv/bin/clearline prospects --research-first
.venv/bin/clearline worker
```

This seeds two curated public leads and queues only Pennsylvania. The worker researches official
sources, persists evidence, then independently qualifies the prospect and drafts an email. Open
**Real-world prospects → Pennsylvania Department of Corrections** to review the linked claims, proposed
channel and pending draft. Approvals reuse the existing simulated outbox; no real recipient is set.

One research run is limited to six hosted web actions and one model response; qualification uses
at most three model turns and no additional web research. Results survive worker/UI restarts.
The live acceptance included one explicit research retry after an unobserved citation was rejected,
and one qualification retry after an unknown reference was rejected. Source references now use
schema-constrained IDs, and rejected typed output is retained for diagnosis. This validates
execution and safeguards, not product efficacy, buying intent, or sales outcomes.

## Streamlit fallback hierarchy and workflow

This section describes only the retained Streamlit fallback. The Next.js navigation is documented
in [frontend migration](docs/frontend-migration.md).

The fallback opens on **Customer Recovery Agent**. **Agents** navigation selects Customer Recovery
or Prospecting. **Monitoring** contains Activity and Outreach history; these support the agents
rather than representing phases of the recovery workflow. Navigation moves into the sidebar on
narrow screens. The page title identifies the agent, numbered headings identify its workflow
steps, and a smaller selected-account label identifies the record being reviewed.

1. **Find recovery opportunities:** run a purchase-history scan or inspect saved scan results.
   Expand **Scan rules & daily automation** to change thresholds, AI limits, or scheduling.
   A scan queues at most the selected number of new AI assessments (default: one).
2. **Review an account:** choose a candidate, inspect revenue and physical-volume changes,
   and read the agent's evidence-backed assessment. For an unassessed account, use
   **Analyze account & prepare email**. The current-status message identifies the next action.
3. **Approve outreach:** review the draft, save any edits, then approve or reject that saved
   version. Approval creates only a simulated outbox entry; no real email transport exists.
4. **Track follow-up & results:** inspect the scheduled follow-up and record a manual demo
   response or outcome when appropriate. Recording an outcome stops automatic follow-ups;
   any follow-up email still requires its own approval.

The numbered links at the top jump to these sections. Portfolio comparisons, source evidence,
and optional restoration scenarios are expandable. Agent assessments remain timestamped
snapshots, distinct from current workflow status. **Refresh results** and execution settings
are in the sidebar. Opening a page never starts an AI job, approves an email, or changes a schedule.

## Agentic portfolio and campaign operations

See [the implementation and throughput report](docs/agentic-workflows.md) for the portfolio
universe, controls, live benchmark, API limits, acceptance results and remaining limitations.

The worker starts fifteen independent async investigations, adapts to returned provider limits,
and halves capacity on temporary rate limits or overload. The target and ceiling are configurable.
One local process and SQLite WAL remain sufficient. High-value or held cases use the configured
high reasoning level; routine cases use medium. No additional servers or queue infrastructure
were introduced. The existing local API and frontend processes are unchanged architecturally.

Overview provides an automatic persisted AI brief and dollar-based segments. Account Intelligence
includes stable, unresolved and CRM-only records as well as recovery signals. Campaigns use
seven shared outreach templates with bounded personalization. Action Center collects campaign
decisions and evidence/contact verification tasks. Agent Activity reports running/queued/completed
work, throughput, elapsed processing time, requests, tokens, estimated cost and batch progress.

See [operational briefing and parallel execution](docs/operational-briefing.md) for the current
AI briefing contract, direct action destinations, 15-way live benchmark and verification results.

## Repeatable Phase 1 demo

The current commercial-5.3 baseline requires verified recipient/relationship evidence before
outreach. The old conversation guides describe historical drafts; use the commercial
pipeline and current acceptance report below for the new execution rules. A separate,
explicitly synthetic fixture verifies sending and replies without authorizing source accounts.

The prepared, isolated demo is ready. See [demo readiness and exact reset steps](docs/demo-readiness.md). Run `.venv/bin/python scripts/reset_demo.py`, then `.venv/bin/python -m clearline.demo serve`; refresh the existing frontend at http://127.0.0.1:3000/. The original database remains separate.

The [customer conversation guide](docs/customer-conversation-demo.md) walks through Lone Tree’s original outreach, a fictional inbound reply, genuine AI interpretation, fresh approval and reset. The account page includes the simulator control; Gmail/Outlook integration remains deferred.

## MCP alternative interface (Phase 1)

The same backend is available at `http://127.0.0.1:8000/mcp` with required authentication and exact-version human approvals. Start the existing demo services, validate with MCP Inspector, then use the authenticated local chatbot. See [setup, authentication and limitations](docs/mcp-integration.md) and [dashboard feature parity](docs/mcp-feature-parity.md). ChatGPT OAuth/Secure MCP Tunnel and ngrok credentials still require account setup; never expose the unauthenticated local dashboard API.


## Commercial decision pipeline (Phases 1 and 2)

The recovery pipeline now separates deterministic detection, tool-based investigation,
commercial strategy, independent decision review, communication preparation and human
approval. A decision to investigate or pursue an opportunity no longer requires an email.
Supported dispositions are contact, internal investigation, human verification, monitoring,
deferral and no action. All source CSVs remain read-only.

Nine categories have persistent `commercial_signals` records: inactivity, purchasing decline,
SKU decline, missed replenishment, distributor-owned purchasing decline, aged open orders,
evidence-backed cross-selling, purchasing obstacles and churn-risk investigation. Multiple
signals describe overlapping evidence; their dollar values must not be added together.
Records retain trigger evidence, amount, assessment status, disposition and next step.

A contact strategy requires a human-recorded recipient/relationship authorization, successful
commercial review, no unresolved blocking prerequisites, a successful communication review
and exact-version human approval. The simulation address grants no commercial permission.
Dashboard, batch and MCP paths enforce the same rules. Earlier drafts and decisions remain
in history but cannot reuse an outdated review. No real email transport has been added.

On an account, record a verified investigation finding or relationship authorization to queue
reassessment. New source evidence and customer responses also invalidate cached decisions.
Timed reviews get a new context key once due; unchanged assessments are reused. The CSV
business clock remains November 1, 2026; simulated conversations and scheduling use the
live clock. Changing the business cutoff requires a deliberate scan configuration change.

### Detection policy and evidence limits

- Inactivity retains the existing rule: at least three direct purchase dates, a gap above 90
  days and above 1.5 times median identified purchasing cadence.
- Account and product deterioration retain the existing strict greater-than-25% threshold
  with at least $1,000 prior comparable-period revenue; product triggers use physical tests.
- Replenishment requires at least four distinct invoice dates, gap variability (coefficient
  of variation) at most 0.5, and elapsed time above 1.5 times the median interval. Recent
  open orders remain explicit counterevidence; a signal is not an instruction to reorder.
- Distributor decline concerns its own bill-to purchases: prior value at least $1,000 and
  a decline greater than 25%. A distributor's buyer is distinct from downstream institutions.
- Open orders aged at least 30 days trigger internal review. This configurable threshold
  is not an invented shipment SLA. Order and credit-led contact require resolutions tied
  to the relevant source lines.
- Product associations use resolved institutional baskets, at least 30 accounts and 10
  paired customers, confidence >=60%, lift >=1.2 and a Wilson lower bound above the
  baseline product frequency. These observational associations are hypotheses, not demand.
- CRM training, contact, funding and product concerns create candidates, not verified
  current needs. Credits and complaints require explanation before implying dissatisfaction.
  Simulated customer requests have separate cited message signals; negation and resolution
  require investigation. Missing source evidence cannot establish contract renewals or SLAs.
- Only `_cents` fields are cents. Raw CSV prices, line totals and catalogue prices are dollars.

### Reproducible validation

`python -m pytest -q` runs deterministic detection and all existing workflow boundary tests.
`npm test --prefix frontend` runs UI tests. `npm run build --prefix frontend -- --webpack`
provides a production build where the local sandbox prevents Turbopack's helper port.

`python scripts/evaluate_commercial_judgment.py --review --env-file /absolute/path/.env`
runs 40 balanced, explicitly synthetic cases. Expected outcomes are fixed before execution;
positive and negative cases are repeated to test consistency. Source fixtures, every failure,
outputs, independent adjudication and API usage remain under ignored `runtime/judgment-53/`.
The independent evaluator receives evidence and the chosen strategy, without the original
supervisor verdict or expected answer. This is a bounded behavioral evaluation, not proof of
real-world conversion performance.

`python scripts/commercial_evaluate.py --all --db runtime/portfolio-evaluation.sqlite3
--baseline runtime/preserved-baseline.sqlite3 --env-file /absolute/path/.env --concurrency 24
--budget 120` evaluates a **separate** preserved portfolio copy. Run the command on one line.
It never sends messages. Cached current decisions are reused, incomplete coverage is explicit,
and billing/budget stops leave recoverable jobs. In-flight calls may finish after the budget
threshold. Do not replace the live database with this copy: use the guarded promotion script
so subsequent human changes and prior approvals/sends remain intact.

`verify_commercial_conversation.py` accepts only a labeled synthetic evaluation identity and
checks the real-model reply, explicit test-input approvals, simulated delivery deduplication
and restoration of a disposable baseline. It must never approve actual portfolio messages.
