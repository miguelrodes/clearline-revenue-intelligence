# Clearline Revenue Intelligence

Clearline helps a salesperson decide which purchasing changes deserve attention and what to do about them. It compares orders with prior buying patterns, checks operational obstacles, and prepares a specific next step. A separate prospect pipeline finds institutions, screens them for product fit, and prepares a first conversation when public evidence supports one. Historical declines and screening scores help allocate sales time. Verified incremental orders would be the measure of commercial success.

## Run the saved demonstration

Use the private reviewer ZIP for a self-contained demonstration. It includes the application, the four fictional case exports in `data/`, a populated combined database in `runtime/phase3/screening.sqlite3`, and the prospect usage ledger. Unzip into a **new directory** and run the commands there. The locked dependencies require Python 3.12 or newer. Setup was tested with Python 3.15 and Node.js 22. The saved demonstration runs without an OpenAI key or worker. [Design document (PDF)](docs/clearline-diagnostics-design-document.pdf)

```bash
mkdir clearline-review
cd clearline-review
unzip /path/to/Clearline-source.zip
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
npm --prefix frontend ci
cp -n .env.example .env
chmod 600 .env
```

**Git alternative.** With access to the private repository, clone `main` and check out the exact commit recorded in the ZIP before adding its demo data.

```bash
git clone --branch main git@github.com:miguelrodes/clearline-revenue-intelligence.git
cd clearline-revenue-intelligence
release_commit=$(unzip -p /path/to/Clearline-source.zip SUBMISSION-MANIFEST.json | python3 -c 'import json, sys; print(json.load(sys.stdin)["base_commit"])')
git checkout --detach "$release_commit"
unzip -n /path/to/Clearline-source.zip 'data/*' 'runtime/*'
```

Then use the dependency and environment commands above, starting at `python3 -m venv .venv`.

Start the API from the project root. It opens the supplied SQLite database and initializes any missing additive schema.

```bash
.venv/bin/python scripts/screening_dev.py api --enable-screening --env-file .env --port 8002
```

In another terminal, from the same root:

```bash
export CLEARLINE_API_ORIGIN=http://127.0.0.1:8002
npm --prefix frontend run build -- --webpack
npm --prefix frontend run start -- --port 3001
```

Open the [Overview](http://127.0.0.1:3001/). The [API health endpoint](http://127.0.0.1:8002/api/health) also reports worker state. A fresh reviewer copy has no running worker. For a live code change, stop the frontend with Ctrl+C and use `CLEARLINE_API_ORIGIN=http://127.0.0.1:8002 npm --prefix frontend run dev -- --port 3001`. Restart the API to pick up backend edits.

## Three-minute sales walkthrough

| Phase | Open | What to show |
| --- | --- | --- |
| 1 · Customer recovery | Overview → Existing customers → a purchasing decline | Compare net invoiced purchases and physical test volumes. Open the account to see the evidence, its buying route and the suggested action. Lone Tree illustrates the purchasing-contact question. |
| 2 · Operational checks and expansion | Action Center → order and credit checks, then Range Line or Juniper Hills | Range Line has an internal fulfillment inquiry. Its saved delivery remains visible while the team waits for findings. For Juniper Hills, a CRM training note gives the rep a specific question to verify. An open order is excluded from completed revenue. |
| 3 · Discovery and screening | Prospect Screening → Discovered online | Five Wyoming institutions came from an official directory. Four await deeper research. Inspect the scoring factors and compare their evidence with the separately labeled fictional agency file. |
| 4 · Research and outreach | Wyoming Medium → saved research and outreach, then Pennsylvania DOC | Wyoming Medium has a researched application and a draft, with purchasing authorization still outstanding. Pennsylvania’s email is ready for human review. Open the saved draft to demonstrate the approval control. |

Opening a saved report, filtering a table and calculating a screening score are local operations. Confirming a new discovery or research run, requesting new reasoning, or recording material evidence that queues reassessment can lead to paid work when a configured worker runs. Human approval applies to an exact message version. Deliveries and entered sales outcomes are simulated. A prospect score conveys investigation priority. Unknown distributor end customers limit attribution, and historic declines do not establish what a salesperson can recover. The [prospect rehearsal](docs/prospect-pipeline-rehearsal.md) records the sources, budgets and limits of the saved run.

## Architecture and live modification

| Component | Responsibility and entry points |
| --- | --- |
| Next.js / TypeScript | Displays the brief, customer checks, candidate pipeline and drafts. Start with `frontend/src/components/sales-surface.tsx` and `prospect-pipeline.tsx`. Shared screens call the local API. |
| FastAPI and MCP | `src/clearline/api.py` and `mcp_server.py` expose the common application services in `services.py`. MCP adds authenticated tool access using the same saved records and approval checks. |
| Python and SQLite | `data.py` reads the CSVs and calculates comparable-period purchases. `screening_rank.py` scores fictional and discovered institutions deterministically. SQLite persists assessments, sources, work, drafts and approvals. |
| Worker and OpenAI Agents SDK | `worker.py` dispatches persisted jobs. The customer and commercial agents investigate accounts, review recommendations and interpret replies. Prospect discovery and research use official public sources and a separate usage ledger. Cached decisions can be reused when their evidence and logic remain current. |

**Optional execution.** To process intentionally requested work, configure a funded `OPENAI_API_KEY` privately in `.env`, inspect the queue in Action Center, and start this single worker from the root:

```bash
.venv/bin/python scripts/screening_dev.py worker --enable-screening --env-file .env
```

This worker processes queued jobs from the combined preview. Automatic scans and portfolio catch-up are disabled in this launcher. Trial new actions in a separate extraction so the original demo stays available.

**Configuration.** The example sets `CLEARLINE_DATA_DIR=data`, `CLEARLINE_DB_PATH=runtime/phase3/screening.sqlite3`, `CLEARLINE_AS_OF=2026-11-01`, and configurable model and reasoning settings. The combined launcher uses that database by default and accepts `--db-path` for an isolated copy under `runtime/`. The agency screening and prospecting spending caps use the standard OpenAI `gpt-6.1-sol` endpoint and its default 30-minute cache pricing. They block requests with unsupported pricing before execution. Frontend builds read `CLEARLINE_API_ORIGIN`; configure it before building.

**Optional MCP.** To enable local authenticated tool discovery, run the first command before starting the API, or restart the API afterward. Then run the second command. The generated `CLEARLINE_MCP_TOKEN` stays in the local environment file.

```bash
.venv/bin/python -m clearline.mcp_client configure
.venv/bin/python -m clearline.mcp_client inspect
```

ChatGPT Web additionally requires a separately installed Secure MCP Tunnel client, an authorized tunnel, and a disposable rehearsal. Its local services use ports 3002/8003 and their own SQLite state. The ZIP does not contain a working tunnel identity, personal credentials or a clone of the private conversation rehearsal. `CLEARLINE_REHEARSAL_ENV_FILE` and `CLEARLINE_TUNNEL_CLIENT` select local paths for that optional integration. The dashboard demonstration above uses 3001/8002.

## Tests

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
npm --prefix frontend test
CLEARLINE_API_ORIGIN=http://127.0.0.1:8002 npm --prefix frontend run build -- --webpack
npm --prefix frontend run typecheck
```

Tests use disposable fixtures. The build generates the route types needed by the type check. This is a supervised local case study with simulated delivery and human approval. Continuous CRM imports, verified revenue attribution and a production email provider are outside its implemented scope.

## Demo delivery controls

For a supervised demo, start the combined preview worker as described above and leave agents paused. To automatically deliver exact, human-approved drafts to the simulated outbox, run `.venv/bin/python scripts/screening_dev.py delivery-on --enable-screening` from the checkout. To stop automatic delivery, run `.venv/bin/python scripts/screening_dev.py delivery-off --enable-screening`. The header shows when delivery is enabled. This mode requires no model key. Investigations, research, post-send reviews and reminders stay queued. A prospect moves to Awaiting response when the simulated outbox records delivery. Use the candidate pipeline's stage filter to find an approved message still waiting for delivery.

To rehearse a customer reply on an active existing account after simulated delivery, open **Customer Conversations → Demo / Testing Controls → Record simulated reply**. Choose the delivered email, enter the fictional reply and save. The reply is linked to that email. Its interpretation stays queued while agents are paused.

## Contents of the reviewer copy

The supplied Clearline institution and sales records are fictional. Real SwabTek prospects have separate public-source evidence. In the reviewer database, personal internal-recipient details are withheld, their saved contact permission is removed, and the corresponding historical delivery retains its original audit hash. Raw provider output, redundant evidence-read logs and machine-specific events are omitted. Saved commercial assessments, usable drafts, historical deliveries, purchasing calculations and source CSVs are retained.

For a fresh local candidate after editing, run the following from the development Git checkout. Use a new output path outside the checkout; the ZIP includes the case data and is intended for the case-study reviewers. Inspect and smoke-test a fresh extraction before sharing it. The manifest records the Git base and each packaged file’s SHA-256; it includes working-tree edits.

```bash
python3 scripts/package_submission.py --data-dir "$HOME/Downloads/clearline-case-study" \
  --output "$HOME/Documents/Clearline Delivery/$(date +%Y%m%d-%H%M%S)/Clearline-source.zip"
```
