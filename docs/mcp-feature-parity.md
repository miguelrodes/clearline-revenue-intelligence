# Dashboard ↔ MCP feature parity

Audit: November 12, 2026. All tools use `ApplicationService` and the existing Store/operations modules. **Bearer authentication is required for every row.** “Human” means explicit informed user intent; message decisions additionally require the saved review and exact confirmation. There is no remote reset, arbitrary SQL, file access or unrestricted database/status mutation.

Verification key: **R** = existing shared-service/HTTP regression coverage; **M** = new MCP transport/adapter test; **L** = live authenticated MCP call; **AI** = real chatbot selected and invoked the tool. Existing automated fixtures use lightweight model responses only to test state transitions; live results below used real AI.

| Dashboard capability | MCP tool(s) | Shared service / rule implementation | Inputs | Additional authorization | Verification |
|---|---|---|---|---|---|
| Overview KPIs, purchasing chart, scope/calculation caveats | `get_portfolio` | `overview`, `portfolio_coverage`; reporting/financial_segments | None | Read | R, L |
| Operational briefing | `get_brief` | `operational_brief`; current_brief | None | Read | R, M, Inspector, AI |
| Refresh briefing | `refresh_brief` | `regenerate_brief`; queue_brief | None | Human request; model usage | R; shared queue wiring |
| Account search, opportunity filters/ranking, contact queue | `query_accounts` | `query_accounts`, `get_opportunities`; operational_queue | Query, namespace, signal, queue, status, actionability, contact state, min cents, sort, offset/limit | Read | R, M, AI |
| Signal drill-down and product/account comparisons | `get_signal_detail` | `signal_page`, `signal_view`; signal_detail | Signal, pagination | Read | R, L |
| Customer summary, current AI decision and uncertainty | `get_account` | `account_view`, `detail`, latest_assessment | Account ID, section, pagination | Read | R, M, AI |
| CRM, products, contacts, aliases, sources and financial evidence | `get_account` (evidence/history) | Same saved evidence and monthly_trends | Account ID, section | Read | R, M, L |
| Exact assigned orders, including open orders | `get_orders` | `account_orders`; audited source rows | Account ID, optional year/status, pagination | Read | R, L |
| Revenue source-record audit | `get_revenue_records` | `transactions`; portfolio_transactions | Year, query, offset | Read | R; shared adapter wiring |
| Account assessment / reassessment | `investigate_account` | `assess`; existing queued agent workflow | Account ID, evidence hash, rerun, UUID | Human request; current evidence and status | R; shared adapter wiring |
| Portfolio/batch assessment | `investigate_portfolio` | `batch`; start_batch | UUID, optional IDs | Human request; active recovery namespace | R, M idempotency |
| Default portfolio refresh | `refresh_portfolio` | `refresh_portfolio`; workbench refresh | None | Human request; queued scan deduplicated | R; shared adapter wiring |
| Custom recovery scan | `run_recovery_scan` | `run_scan` | Scan rules/assessment limit, UUID | Human request; validated thresholds | M |
| Grouped Action Center and account action context | `list_actions` | `action_groups`, `work`; work_groups | Optional group ID, pagination | Read | R, M |
| Internal checks and prepared CSV export | `get_verification_request` | `check_detail`, `check_export`; review_checks | Check category, optional signal/account, include_csv | Read; copying does not resolve/send | R; shared adapter wiring |
| Prepare a selected group / simulated role inboxes | `prepare_outreach` | `campaign`; create_campaign | Name, account IDs, UUID, simulated_contacts | Human preparation request; explicit simulator choice | R, M idempotency, AI |
| Campaign list, progress and members | `get_campaigns` | `campaign_page`; campaign_view | Optional ID, pagination | Read | R, L |
| Campaign customer responses | `get_campaigns` (responses_only) | campaign membership + `conversation` | Campaign ID, responses_only, pagination | Read | L, AI; response on the explicitly approved two-account campaign |
| Read exact draft and rationale | `get_draft` | `draft`; Store.draft_hash | Draft ID | Read | R, M, L |
| Edit a draft | `edit_draft` | `edit`; Store.revise_draft | ID, current version, full message fields | Human edit request; creates new unapproved version | R, M; dashboard sees MCP edit |
| Reassess/regenerate message | `regenerate_draft` | shared regeneration + existing initial/follow-up/reply agents | ID, version, UUID | Human request; pending drafts only; racing edits invalidate result | M including reply regeneration; no separate agent |
| Review selected exact messages | `review_outreach`, `get_approval_review` | persistent approval_reviews + draft_hash | Draft IDs / review ID | Read/prepare review only; does not approve | M, L |
| Individual or selected bulk approval/rejection | `decide_outreach` | `decide_review`; Store._decide | Review ID, decision, exact confirmation | **Human confirmation of full messages**; all-or-nothing validation, expiry, current holds | M: stale, held, expiry, rejection, atomic rollback and duplicate confirmation. L: two exact messages explicitly approved by user and sent to simulator |
| Execute approved simulated deliveries | `execute_approved_sends` | `approved_sends`; existing delivery queue/provider | Approved draft IDs | Existing exact approval; no additional delivery created | M, L; both approved jobs completed once |
| Customer conversation and incoming AI response | `get_conversation` | `conversation`; SimulatedProvider | Account ID | Read | R, M, L, AI |
| Simulate incoming response and start analysis | `simulate_customer_reply` | `inbound`; SimulatedProvider.ingest + reply worker | Account, parent outbound ID, external message ID, body | Explicit fictional-test request; valid parent; deduplication | R, M, AI + real response agent, visible in Next.js |
| Proposed reply and extracted facts | `get_conversation`, `get_account`, `get_draft` | saved reply interpretation, commercial task, unapproved draft | Account/draft ID | Read | R, M, L, AI |
| Record outcome / sales status | `record_outcome` | `outcome`; Store.record_outcome | Account, kind, note, optional cents/reference | Human-provided outcome; manual-demo provenance | R; shared adapter wiring |
| Acknowledge/defer/reject recommendation | `review_account_status` | `disposition`; review_recommendation | Account, decision, note | Human request; cannot clear source holds | R; shared adapter wiring |
| Observed commercial performance | `get_performance` | `performance`; recovery_performance | Namespace | Read; simulation and causal limits retained | R; shared adapter wiring |
| Job and scheduled-follow-up lists | `list_jobs` | `list_jobs`, `jobs` | Status/kind/account, pagination | Read | R, M |
| Job results, decision events and errors | `get_job` | `job_result`; saved events/draft IDs | Job ID | Read | R, M |
| Cancel/retry work and follow-ups | `manage_job` | `job_action`; cancel_job/retry | Job ID, action | Human request; eligible statuses only | R, M |
| Agent activity, tokens/cost, worker and batch status | `get_agent_status` | health/execution/batches | None | Read | R, M, Inspector, L |
| Pause/resume new work | `set_worker_state` | `worker_action`; Store.set_paused | Pause/resume | Human request | R, M |
| Daily scan schedule/rules | `set_scan_schedule` | `schedule`; Store.schedule | Enabled + scan rules | Human request | R, M |

## Deliberate boundaries

No dashboard business operation was intentionally omitted. Some live mutations (opt-out, lost sale, schedule change, portfolio-wide rerun) were covered by regression tests rather than altering the user's demo simply to exercise each tool. Those rows are not claimed as individually live-tested. The exact confirmation gate must also be respected by each external chatbot host; tool annotations and descriptions are guidance, not proof of human consent. The included interactive client enforces an independent human approval interruption.

The interface does not verify fictional purchasing contacts from the public web, clear financial/identity holds without source correction, connect real mailboxes, modify source CSVs, or make claims of causal revenue recovery. These are existing product boundaries, not MCP omissions.

## Live test record

- Official Inspector: authenticated discovery, briefing and agent-status calls succeeded. Anonymous/incorrect-token requests fail; the existing dashboard mutation guard remains intact.
- A real OpenAI chatbot called briefing → search → account investigation.
- Another real chatbot turn selected two actionable uncontacted inactive accounts and created **MCP recovery review** (`d602b602dc7d469296309179a6b75929`). Both preparation jobs completed. Lone Tree v2 appeared in Next.js; Antelope v1 was reused from current saved work.
- Full exact messages were presented and explicitly approved by the user. Antelope v1 and Lone Tree v2 completed simulated delivery to `simulation@example.invalid`, once each. A subsequent simulated Lone Tree training request was interpreted by the real agent; the prepared response remained unapproved. The real chatbot and Next.js read the same conversation/campaign result.
- Independently, a real chatbot attached a fictional training request to Cedar County's existing approved simulated outbound. Job `005647491f0b42ae93519ebcf5a4fd11` completed with real AI: training need, quoted evidence, support-needed conversation state, a next-step task and a new unapproved reply. Both MCP and Next.js display this state. No new outbound was sent for this test.
- All local reports/transcripts are under ignored `runtime/mcp/`. The original database and case-study CSVs are not modified or uploaded by this integration.
- The rehearsal is archived and the baseline restored: 51 pending recovery drafts, 2 pre-existing recovery sends, no new test sends, Lone Tree v1 ready again. Original data is unchanged.
- ChatGPT connection remains unverified: the official Secure MCP Tunnel client and authenticated launcher are ready locally, but the tunnel ID/runtime key and workspace setup are missing. Notion read/update remains blocked by a connector error.
