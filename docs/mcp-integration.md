# Phase 1: dashboard and MCP

The Next.js dashboard and MCP are two interfaces to `ApplicationService`. They share the existing SQLite session, Python agents, worker, approval hashes and simulated provider. MCP uses the official Python SDK 2.3 (`MCPServer`, the SDK's renamed `FastMCP`) over Streamable HTTP at **http://127.0.0.1:8000/mcp**.

## Start locally

From `/Users/miguelrodes/Code/clearline-revenue-intelligence`:

```bash
# Already configured on this machine. Generates a private token without printing it.
.venv/bin/python -m clearline.mcp_client configure

# Terminal 1: existing disposable demo, backend, MCP and worker together.
.venv/bin/python -m clearline.demo serve

# Terminal 2: dashboard (the existing build is sufficient).
npm --prefix frontend run start

# Terminal 3: authenticate and test independently, before starting a chatbot.
.venv/bin/python -m clearline.mcp_client inspect
.venv/bin/python -m clearline.mcp_client inspect --method tools/call --tool get_brief

# Terminal 3: real conversational interface using the configured OpenAI API model.
.venv/bin/python -m clearline.mcp_client chat
```

Do not start a second backend/worker while `demo serve` is running. Stop it with Ctrl+C or `.venv/bin/python -m clearline.demo stop`. Reset remains a local developer command, not an MCP tool. Reset archives the current rehearsal; it does not update the original data.

The Inspector launcher pins Inspector 2.15.0 and supplies an isolated supported Node 24.22.1 runtime through npm. It passes authentication in a temporary mode-0600 configuration file, not in command arguments. It removes that file on exit and saves token-redacted results under ignored `runtime/mcp/`.

`CLEARLINE_MCP_TOKEN` is stored only in ignored `.env` (mode 0600); no value is printed. `CLEARLINE_MCP_URL` defaults to the local endpoint. The chatbot uses the existing `OPENAI_API_KEY` and configurable `OPENAI_MODEL`. Never paste secrets into a conversation or commit them. Rotating the token revokes previous local-client access after restart.

## Authentication and ChatGPT

All MCP requests, including discovery, require a valid bearer token. A missing or short configured token fails closed. The SDK verifies authentication before transport processing, uses stateless requests and retains host/origin checks. This is a single-owner local/demo adapter, not a production OAuth implementation. The ordinary dashboard API remains loopback-only and must not be exposed wholesale.

**ChatGPT is not connected yet.** ChatGPT custom plugins cannot supply an arbitrary bearer API key. For the requested private tunnel path, the official client supports injecting our existing bearer credential into its local MCP requests, while OpenAI organization/workspace permissions govern tunnel access. This preserves server authentication but provides a shared application identity, not per-user OAuth. ChatGPT authentication configuration and workspace policy still need verification; do not remove server authentication or expose the endpoint publicly. [OpenAI authentication requirements](https://developers.openai.com/plugins/build/auth).

The implemented, verified fallback is the authenticated local chatbot above. It calls the real API and MCP tools; it is an interface, not a second revenue engine. One prompt is bounded to eight model turns and 180 seconds. `--prompt "..."` supports bounded noninteractive demonstrations; it rejects attempted message approvals. Interactive mode adds an independent SDK approval interruption, displays the saved exact messages, and requires the human to type the matching review confirmation before any approval tool executes.

To connect ChatGPT later:

1. Configure an established OAuth provider with proper audience/scopes and integrate its token verifier, **or** provision a Secure MCP Tunnel in the correct OpenAI Platform organization and ChatGPT workspace. The latter also needs the tunnel client/runtime credential and an authenticated connection to this local endpoint; do not disable this server's authentication.
2. In ChatGPT, open Plugins, choose **+ → Add custom MCP server**, select URL or Tunnel, configure its supported authentication, create/install the plugin, and test a read-only briefing first. Workspace administrators may restrict this option. [Custom MCP setup](https://developers.openai.com/api/docs/guides/custom-mcp-server).
3. Keep approval confirmation enabled for `decide_outreach`. An external host must obtain human consent; an MCP server cannot independently prove what a human typed in another product.

### Secure MCP Tunnel: isolated rehearsal

The existing Apple Silicon `tunnel-client` v0.0.20 is installed at `~/Code/clearline-revenue-intelligence/runtime/bin/tunnel-client`. The launcher resolves that installed binary when this integration checkout has no local copy. It verifies the backend’s disposable-demo status through authenticated MCP and forwards only to `http://127.0.0.1:8003/mcp`, the conversation rehearsal. It reads that rehearsal’s existing MCP bearer token from the local Code checkout `.env`. Discovery and regular MCP requests use the bearer token through an environment reference. The runtime key and local MCP token are not placed in command arguments, raw HTTP logging is disabled, and remote administration is disabled.

User setup:

1. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels) in the intended organization. Create a private tunnel and associate it with the ChatGPT workspace intended for this demonstration. Creating it requires Tunnels **Read + Manage**; running/selecting it requires **Read + Use**. A personal Platform organization does not automatically grant access in the Northeastern Edu workspace.
2. Create a separate restricted runtime key in [Platform API keys](https://platform.openai.com/settings/organization/api-keys), with Tunnels **Read + Use**, not an admin key. In Terminal, run this helper from the integration checkout. It prompts without echoing the values and saves them to the ignored local `.env` with owner-only permissions:

   ```bash
   cd "/Users/miguelrodes/Documents/New project/clearline-integration"
   PYTHONPATH=src /Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/configure_secure_mcp_tunnel.py
   ```

   Do not paste the values into chat, shell commands, screenshots, or Git. The local MCP token and OpenAI model API key remain separate.
3. With the isolated rehearsal API running on port 8003, validate and then start the foreground client:

   ```bash
   PYTHONPATH=src /Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/start_secure_mcp_tunnel.py doctor
   PYTHONPATH=src /Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/start_secure_mcp_tunnel.py run
   ```

   Keep it running during ChatGPT discovery and every tool call. Check `http://127.0.0.1:8080/readyz` and `/ui` for readiness and active polling. A passing local test does not establish remote tunnel readiness.
4. In [ChatGPT Plugins](https://chatgpt.com/plugins), add a custom MCP server with **Connection: Tunnel**, select the same tunnel and install the private plugin. Confirm organization/workspace scope and the authentication settings before granting access. This application still requires its local token. If the workspace requires user OAuth, configure a supported OAuth provider rather than weakening authentication; this remains a setup decision, not a completed integration.
5. Ask “What are my top priorities right now?” The default `get_brief` reports named customer and prospect actions, internal inquiries awaiting findings, and active scheduled follow-ups. `list_actions` shows the same priorities and can open a group. Use `get_brief(view="saved_brief")` to inspect the earlier recovery briefing. Keep confirmation enabled for write tools, particularly `decide_outreach`, so each exact message requires human approval.

ChatGPT workspace access, remote discovery, and a real ChatGPT tool call must still be checked after the tunnel client reports healthy polling. [Official Secure MCP Tunnel setup](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

## Ngrok: restricted authenticated clients

Ngrok 3.37.2 is installed, but startup currently fails with **ERR_NGROK_4018** because no account credential is configured. No public tunnel was opened.

Configure your ngrok account credential locally following the dashboard instructions; never paste it into chat. Then, with `demo serve` running:

```bash
.venv/bin/python scripts/start_mcp_tunnel.py
```

The launcher verifies through authenticated MCP that the running backend uses the registered disposable demo database. It starts:

```bash
ngrok http 8000 --host-header=localhost --inspect=false --traffic-policy-file scripts/ngrok-mcp-policy.yml
```

`--host-header` is accepted by the installed ngrok version, with a deprecation warning. The checked-in policy blocks every path except `/mcp` and `/mcp/`. MCP still requires its token. Request inspection is disabled to avoid storing customer payloads/authentication headers. The public URL is `<assigned HTTPS address>/mcp`. Set `CLEARLINE_MCP_URL` locally to use it with the authenticated client or Inspector. This does **not** make bearer authentication compatible with ChatGPT.

Before using an external connection, verify anonymous `/mcp` gets 401, all other paths (including `/api/overview`, `/docs`, `/openapi.json`) get 404, and authenticated discovery works. These public checks remain unverified until the ngrok credential is configured. Never replace this command with an unrestricted tunnel to port 8000 or 3000. Close the tunnel with Ctrl+C after the demonstration. [Ngrok path blocking](https://ngrok.com/docs/gateway/traffic-policy/actions/custom-response).

## Review and execution workflow

1. `get_brief` → `query_accounts` → `get_account` / `get_orders` retrieves saved priorities and evidence.
2. `prepare_outreach` queues selected recovery accounts, using existing assessments when valid. Explicit `simulated_contacts=true` permits fictional role inboxes. Preparation never approves. Request UUIDs prevent duplicate campaigns on retries.
3. `get_campaigns` / `get_job` retrieves progress. The resulting drafts appear immediately in Next.js.
4. `review_outreach` captures exact draft IDs, versions, recipients, subjects, bodies and evidence hashes in SQLite for 30 minutes. Show all messages to the human. `get_approval_review` can retrieve the same review after reconnecting.
5. Only after explicit confirmation, `decide_outreach` validates every snapshot and current restriction in one transaction. A single stale/held item rejects the entire selection. Repeated confirmation returns the saved result without another approval/send. Editing or regenerating requires another review.
6. Approval queues delivery. `execute_approved_sends` returns those existing jobs/outbox records; the worker performs the same idempotent simulated send used by the dashboard.
7. `simulate_customer_reply` attaches an explicitly fictional reply to an existing outbound message and queues the real response agent. Follow-ups stop. `get_conversation` and `get_account` expose validated facts, interpretation, next action and any unapproved reply draft.
8. `record_outcome`, `review_account_status`, `manage_job`, worker and schedule tools mirror the supported dashboard operations. Source holds cannot be cleared through an arbitrary status update.

All money is integer cents. Signal groups overlap. Historical decline is not forecast recovery; product reductions do not offset growth in other products. Simulated interest is not verified or incremental revenue. Real prospect records never join fictional recovery orders.

## Coverage and evidence

See [the feature-parity checklist](mcp-feature-parity.md). No existing dashboard business capability is intentionally omitted. Draft regeneration is additionally exposed through the shared service and HTTP endpoint without adding frontend controls. Developer reset, file access, arbitrary SQL, unrestricted status editing, database maintenance and real email transport remain unavailable remotely.

Automated checks validate transport/authentication, typed schemas, shared reads, two-way dashboard state, exact-version review, expiry, rejection, atomic bulk rollback, current holds, duplicate request/send prevention, regeneration races, reply regeneration and follow-up/job controls. Production-data writes are not part of these tests.

The implementation is local and unpushed. Notion's connector currently returns `Unknown tool (notion.fetch)`; the precise pending plan update is preserved in `docs/notion-update-pending.md`.

## Verification result (November 12)

34 tools are documented in the parity checklist. 127 backend tests, 32 frontend tests and TypeScript passed; SQLite integrity is `ok`. The dashboard frontend was not changed, so its existing production build was reused. Four real local-chatbot conversations made 11 model requests (53,874 input / 1,191 output tokens). Using the configured model's standard rates before cache discounts gives an upper estimate of $0.119658; the real customer-response job recorded $0.008818. Those figures exclude any independently scheduled briefing refreshes and are estimates, not invoice totals.

After the user explicitly approved Antelope v1 and Lone Tree v2, a fresh exact-message review was created and both approved messages were delivered once to `simulation@example.invalid`. A simulated Lone Tree training request then triggered one real response-agent call, which completed in approximately 6.7 seconds, extracted quoted facts, stopped the existing follow-up, and prepared reply v3 awaiting human approval. That reply was not approved or sent. A real local chatbot read back the conversation and campaign response, and Next.js showed the same result.

The added readback used 2 model requests, 10,040 input and 289 output tokens (estimated $0.022970 before cache discounts). The reply-agent event recorded $0.008342. Combined incremental estimate: **$0.031312**, excluding independent briefing refreshes. Twenty focused MCP/tunnel-launcher tests passed (the earlier full validation was 127 backend tests, 32 frontend tests and TypeScript).

The rehearsal was archived to `runtime/demo/history/5529f660c0864c8dbfe167dad41cfb99.sqlite3`, then the original demo baseline was restored. Verified: 51 pending recovery drafts, 2 pre-existing recovery outbox entries, zero outbox entries from these two new approvals, Lone Tree v1 awaiting approval again, SQLite integrity `ok`, and unchanged original database file. The demo API/worker was restarted; authenticated MCP discovers 34 tools and anonymous requests still return 401. Old rehearsal approvals are not reused after reset. No real email or GitHub push occurred.

Evidence: `runtime/mcp/approved-live-review.json`, `simulated-send-result.json`, `approved-e2e-get_job.json`, `approved-e2e-get_conversation.json`, `chat-approved-e2e-readback.json`, `approved-e2e-final-state.json`, `approved-e2e-restored.json` and `approved-e2e-usage.json`. These are local ignored files, not repository uploads.
