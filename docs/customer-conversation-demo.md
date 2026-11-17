# Customer conversation rehearsal

Open [Lone Tree in the isolated preview](http://127.0.0.1:3002/accounts/c966fd651cca1e9020fa). The combined preview has its own database and runs on ports 3001 and 8002. The rehearsal uses ports 3002 and 8003 with the same Next.js interface, FastAPI, SQLite and customer workflow.

## Run the conversation through ChatGPT Web

Select **Clearline Demo** in a fresh ChatGPT Web conversation. The dashboard is optional. The opening message is:

> Use Clearline Demo. What should I do to recover sales from ID DOC – Lone Tree in Idaho? Show the purchasing change, what is blocking outreach, and my next step. Read the saved records and stop before making any changes.

| Step | What to say or check | MCP tools |
| --- | --- | --- |
| 1. Retrieve | Expect a $50,225 January–October purchasing decline and a check for the purchasing contact and buying route. Two older draft versions are superseded. | `query_accounts`, `get_account` (summary and evidence), `get_orders` |
| 2. Verify | Use the verification message below. The result should identify the resolved contact check and one Lone Tree assessment job. | `record_contact_authorization`, `get_job` or `list_jobs` |
| 3. Review | “When that job finishes, show me the latest recommendation, why it was chosen, the exact subject and entire email body, the intended contact, and the simulator destination. Wait for my decision.” If the job recommends a hold, ask for its reason. | `get_job`, `get_account` (summary and drafts), `get_draft`, `review_outreach` |
| 4. Edit or approve | Optionally request specific edits first. Let any edit quality check finish and review the latest version. In a separate turn, say “I approve **the version you just showed me** for simulated delivery.” | `edit_draft`, `list_jobs`, `get_draft`, `review_outreach`, then `decide_outreach` with the current review ID |
| 5. Confirm delivery | “Show the saved receipt, where it went, and the account status.” Expect one outbox record for that approved draft, delivered to `simulation@example.invalid`, and **Awaiting response**. | `execute_approved_sends` (reads delivery status), `get_account` (outbox), `get_conversation` |
| 6. Supply a reply | “Treat the following as a fictional reply to the delivered Lone Tree email. Record my exact words once, then tell me when interpretation finishes.” Append your own reply. The tool links it to the outbound message ID and deduplicates retries using the same caller-generated message ID. | `get_conversation`, `simulate_customer_reply`, `get_job` |
| 7. Read the decision | “What changed with Lone Tree, and what should I do next? Show the saved interpretation, restrictions, any active reminder or draft, and how today's priorities changed.” Check the newest conversation and current job state. | `get_conversation`, `get_account`, `list_jobs`, `get_draft` if present, `get_brief`, `list_actions` |

**Verification message for step 2**

> For this fictional rehearsal, I verify and authorize purchasing.lonetree@example.org as the Current purchasing coordinator for Lone Tree. The buying route is Direct. Evidence: “Synthetic rehearsal only. The internal purchasing directory and fictional permission record confirm this coordinator can discuss resuming direct purchases of CL-MAIL50 and CL-FS10.” Record this against the pending purchasing-contact check. Let its one targeted reassessment run, then show me the result. Stop before approving anything.

An email address alone cannot clear the check. When reviewing a draft, the intended contact is `purchasing.lonetree@example.org`; the simulator receives the approved text at `simulation@example.invalid`. A changed draft requires a new review and human approval. If a job is still running, ask ChatGPT to check that same job ID. A second investigation is unnecessary.

## Replay three different replies

Wait until the active job finishes. **Before each scenario**, run the sent-checkpoint command below on your Mac and open a fresh ChatGPT conversation with Clearline Demo. Ask “Show Lone Tree's delivered email and pending reminder.” Each replay should show the same approved **version 3**, subject **Lone Tree: current requirements for CL-MAIL50 and CL-FS10**, one simulated delivery, and no incoming reply. This checkpoint contains the previously delivered message even if the live contact-verification exercise generated different wording.

Then follow steps 6 and 7. Use any text you like. Compare the resulting action with these expectations:

- **Renewed interest.** Give the new coordinator's reply and express interest in discussing current requirements. Look for a relevant next step, with any new draft awaiting approval.
- **Distributor transition.** Say the institution still uses the products and now buys through a regional distributor. Check that direct reorder outreach stops and the agent recognizes the buying-route change.
- **Explicit opt-out.** Say the institution switched suppliers and wants no further contact from Clearline. Check the saved restriction, canceled reminders, and absence of a sendable draft.

For permission and finances, `get_agent_status` shows the worker and its **rehearsal_budget**. The new interactive session has a $2 cumulative ceiling across assessments, edit reviews, and reply interpretation. The worker reserves the maximum priced cost of each request before dispatch and settles it from returned usage. Pending or indeterminate charges block further paid requests. Restoring either checkpoint preserves charges and reservations. If a job reports **blocked_config**, read its reason and remaining budget. These limits apply only to this conversation rehearsal.

## Optional dashboard walkthrough

1. In **Next Action**, open the purchasing-contact check. The form reuses saved details and asks for the missing prerequisites. For this fictional exercise, use `purchasing.lonetree@example.org`, role **Current purchasing coordinator**, and **Direct**. For the evidence, enter “Synthetic rehearsal only. The internal purchasing directory and fictional permission record confirm this coordinator can discuss resuming direct purchases of CL-MAIL50 and CL-FS10.” Saving only the email leaves the check open. Choose the verification action after supplying the role, route and evidence.
2. Stay on the account. The worker reviews the new information and the page updates automatically. A commercially justified draft appears under **Next Action**. Read it, choose **Approve simulated send**, then **Confirm**. Any edit requires approval of the exact updated version. Delivery is recorded at `simulation@example.invalid`.
3. To simulate an incoming reply, use the connected ChatGPT rehearsal as described above. **Customer Conversations** on the profile shows the recorded exchange and its AI interpretation.
4. Below the customer’s name, choose **Pause outreach** for a temporary hold or **Do not contact** to record an opt-out for one recipient or the entire account. Record the reason. A pause can have a reconsideration date and requires manual resumption.

[Cedar County](http://127.0.0.1:3002/accounts/9eac704f6ec1cf882ead) has an earlier delivered email and supports a simulated reply. [Sheridan County](http://127.0.0.1:3002/accounts/4fffd02df80780e4c74c) has a no-action decision and no outbound email to reply to. Later-phase evidence is available in [Prospect Screening](http://127.0.0.1:3002/screening) and the saved [Pennsylvania prospect profile](http://127.0.0.1:3002/accounts/2dc5f09907f6e34e3171).

## Reset or start the rehearsal on this Mac

Run these commands from Terminal. They stop only the registered rehearsal, restore its original copy, and start its services. Resetting uses zero model calls. Leave the Terminal window open while using the demo.

```sh
cd "/Users/miguelrodes/Documents/New project/clearline-integration"
/Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/conversation_demo.py reset --start --env-file /Users/miguelrodes/Code/clearline-revenue-intelligence/.env
```

To start each reply replay directly after the approved email, run the following from the same directory in an available Terminal window. Wait for the services to start before reading the account again in ChatGPT.

```sh
/Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/conversation_demo.py reset --sent --start --env-file /Users/miguelrodes/Code/clearline-revenue-intelligence/.env
```

To finish at the original missing-contact baseline, run the first reset command again. To restart services while keeping current work, use `serve` after stopping the rehearsal. The worker takes new assessments, replies, edit reviews, and approved simulated deliveries for the accounts registered in the rehearsal budget. Lone Tree is registered initially. To select or replace the second existing customer, pause and stop the rehearsal, run `scripts/conversation_demo.py select-account --account-id ID` with the project Python, then use `serve`. The cumulative $2 cap and all recorded charges carry across selections. To run just one queued assessment, reply or revision while the rest stay paused, stop the rehearsal, select the account, and run `scripts/conversation_demo.py run-job --job-id ID --env-file ENV_FILE` before restarting with `serve`. It leaves inherited jobs and scheduled reminders in place for inspection. All reply interpretations use the real agent and the actual text entered.

For a fresh checkout with the source-derived combined database present, initialize and build before the first start. Use the project’s existing Python environment.

```sh
python scripts/conversation_demo.py init
(cd frontend && CLEARLINE_NEXT_DIST_DIR=.next-conversation CLEARLINE_API_ORIGIN=http://127.0.0.1:8003 npm run build -- --webpack)
```

The initial snapshot and session live in the ignored `runtime/phase12-acceptance/conversation-demo/` directory. The launcher checks the registered paths and the selected checkpoint checksum. A fresh setup also needs an existing human-approved outbound checkpoint before registering its budget once with `scripts/conversation_demo.py budget-init`. This Mac is already registered. Both the historical acceptance ledger and the separate interactive ledger stay in that directory across resets. Use `scripts/conversation_demo.py budget-status` with the project Python for the current balance.
