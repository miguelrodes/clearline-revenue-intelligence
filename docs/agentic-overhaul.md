# Commercial intelligence overhaul — commercial-5.3

Validated locally on November 13, 2026. The current implementation separates discovery,
investigation, strategy selection, independent decision review, action preparation and
human approval. Contact is one possible intervention; internal work, verification,
monitoring, deferral and no action do not require an email.

## Current acceptance results

- All 486 source account records have current reviewed assessments. Every active signal
  has exactly one documented disposition; the current dataset contains 1,057 signals.
- 252 accounts require human verification, 83 require internal investigation, 11 are
  monitored and 140 receive no action. No source-account email is currently commercially
  eligible: the supplied records contain no verified recipient/relationship authorization.
  This is a business-data limitation, not a claim that all opportunities lack value.
- The 245 old recovery drafts retain their exact text and history. Their replacement
  decisions are 143 verification, 65 internal investigation, 9 monitoring and 28 no action.
- The 92 old channel drafts comprise 3 distributor buyers, 41 institutions with direct
  purchase history, and 48 distributor-only institutions. Replacement decisions are
  51 verification, 22 internal investigations, 5 monitoring and 14 no action.
- Source CSV hashes, financial totals, approvals, outbox entries, messages and outcomes
  match the preserved before-state. Existing source ambiguities were not silently resolved.

| Capability | Detected records, all assessed |
| --- | ---: |
| Inactive recovery | 53 |
| Partial purchasing decline | 204 |
| Product deterioration | 366 |
| Missed replenishment | 58 |
| Distributor own purchasing decline | 1 |
| Aging open orders | 45 |
| Cross-sell candidates | 177 |
| Purchasing obstacles | 108 |
| Credit/relationship-risk investigation | 45 |

These counts overlap and some categories contain multiple records per account. The existing
Overview charts retain their narrower display segments (for example, partial decline excludes
inactive accounts), so those customer counts are not the full signal-record counts above. Associated
amounts are not additive or forecasts. Product ownership now uses all supplied invoices,
including dates outside the two comparison windows. Associations remain hypotheses requiring
customer relevance; CRM concerns are not assumed to be current.

## Commercial evaluation and limitations

The final expanded evaluation scored **44/44 (100%)** against expectations fixed before execution:
22 positive cases and 22 negative cases, spanning all nine action categories. There are 41
unique anonymized evidence sets; four identical healthy controls are retained and reported,
not portrayed as four independent situations. The additional cases cover exact decline and
order-age boundaries, price increases hiding falling quantities, irregular ordering, and
previous product ownership outside comparison periods. These are bounded synthetic checks,
not proof of real-world revenue uplift.

The earlier repeated-scenario evaluation remains available: 38/40 (95%), with two disagreements
about undated training notes after recent contact. The expanded suite explicitly expects
verification when current need is not established; that expectation was set before the new run.
Both the original misses and the expanded sources/results are preserved.

Fresh-context evaluation accepted all 44 final strategies with zero critical failures. All eight
named portfolio regressions also passed independent review. The first named review reported a
Juniper Hills failure because the evaluator input omitted persisted task state. That failed report
is retained alongside the corrected input and repeated 8/8 review. Reviewers see evidence and
final strategy without the original supervisor verdict or expected answer; this is independent
context using the configured model, not a claim of model-family independence.

Range Line now investigates its own aging orders before outreach. Granite Falls investigates
the credit. Kimball checks what its recent contact resolved despite purchasing growth.
Boulder Ridge receives no same-day-overdue email. Hawk and Juniper use training evidence
without inventing a current request; Lone Tree prioritizes the purchasing handoff; Iron
preserves the distributor route. Actual authorization remains missing in each contact candidate.

## Reliability and controls

- 277 backend tests and 46 UI tests pass; the production build passes using Webpack.
- Positive/negative detection fixtures pass completely, including same-day orders, irregular
  cadence, product ownership outside comparison periods, weak associations and healthy accounts.
- Individual, grouped and MCP approval paths enforce the same exact-version, evidence,
  recipient and prerequisite checks. A simulated address grants no relationship permission.
- Approval-only bookkeeping cannot become a circular prerequisite to preparing a proposal.
  Real missing-business-fact tasks remain blocking. Pending tasks can be reused by their ID
  and exact evidence scope; a changed task cannot silently overwrite another investigation.
- Source changes, responses, verified findings, authorization and meaningful elapsed time
  invalidate cached reasoning. A new noncontact strategy cancels unexecuted follow-ups,
  retaining prior sends and approvals. Retry/backoff is persistent; rate limits and clustered
  provider failures reduce concurrency, without treating one gateway error as a quota limit.
- A real-model synthetic conversation passed initial approval, simulated delivery, inbound
  training request, useful reply generation, fresh approval, duplicate prevention and reset.
  No portfolio email was approved by the implementation or evaluation scripts.
- The full 486-account import and baseline capture/reset passed both rehearsal and live checks.
  The guarded import skipped no accounts, preserved all original activity, backed up the session
  and archived the previous reset baseline. The final baseline includes the new decisions and briefing.
- Live HTTP and authenticated MCP reads pass; all 38 tools remain available under the same local
  authentication and approval controls. Unauthenticated MCP requests return 401. This does not
  establish an external ChatGPT tunnel connection.
- Browser checks verified current account recommendations, finding/authorization controls,
  grouped tasks and correct empty-outreach states. Action groups now separate orders/credits,
  contacts/routes, training/product needs and other facts. Group counts overlap; they cover 335
  current investigation/verification accounts. Dormant prerequisites remain in account history.
  No UI download control is invented for these groups.

Recorded estimates are $59.10 for portfolio assessment/corrections and named reviews, and
approximately **$73.24 total** including development trials, all evaluation runs,
synthetic conversations and live brief generation. These use provider usage and configured
prices, not a billing invoice; failures without returned usage may be undercounted.
`runtime/commercial-v5/expanded-evaluation-summary.json` records the components.

Reproduce the final judgment set with `scripts/evaluate_commercial_judgment.py --review` and
`--review --supplemental --output-dir runtime/judgment-boundary`; both accept `--env-file`.
These create isolated synthetic fixtures and never approve or send portfolio emails.

Private evidence is in `runtime/commercial-v5/`: portfolio acceptance, both independent named
reviews, the full synthetic evaluation, conversation/reset results, preserved snapshots and
promotion records. No credentials or original CSVs are copied into tracked source files.
No GitHub push, cloud deployment or real email integration is part of this change.

## Review and next steps

Review the account recommendations and missing-business-fact tasks for Range Line, Hawk,
Lone Tree, Juniper Hills, Iron and Boulder Ridge. Record only genuine findings and recipient
relationship evidence; those actions trigger reassessment. Do not use a fabricated contact
in the source portfolio to make the approval queue look populated. The separate labeled
synthetic conversation fixture demonstrates the complete approved-send/reply workflow.
Real fulfillment status, current customer needs, recipient authority and commercial terms
remain unverified where the supplied data does not establish them.

---

> Historical implementation report for recovery-4. The commercial-5 overhaul above supersedes its execution rules; these earlier results are retained as the before-state.

# Phase 1 agentic recovery overhaul — November 13, 2026

Implemented, evaluated and imported into the local demo. All 486 recovery account records have current `recovery-4` assessments. The original CSVs, financial methods and demo baseline are unchanged. No real messages, GitHub push or cloud deployment occurred. Private execution evidence remains in ignored `runtime/overhaul/`.

## Proven causes and architectural decision

The audit inspected 28 varied accounts and traced four genuine old-agent executions through persisted prose. Hawk County's model identified night-shift training, but a template removed the specific intervention. Lone Tree's contact-handoff strategy became a generic question. Juniper Hills could see an order warning but could not retrieve its underlying rows. Iron County was asked to obtain unavailable distributor sell-through data. Restricted strategy names, blanket holds, incomplete conversations/CRM joins, aggregate-only cache keys and absent independent commercial review compounded these problems.

One tool-using investigator now combines investigation, commercial strategy and message preparation. A separate fresh-context reviewer checks the proposal and can retrieve more evidence. At most two targeted revisions are allowed. Structured-output failures receive bounded repair feedback. Unresolved failures remain explicit jobs; there is no canned fallback or Python rewrite of approved model prose. Four serial specialists were rejected because they would duplicate context without demonstrated benefit.

Six scoped tools retrieve: audited account overview; paginated original purchase rows; full CRM, conversations, outcomes and tasks; identity candidates; supplied product catalogue; prior assessments and drafts. Original row references, calculations, customer statements, hypotheses and missing information remain distinguishable. Retrievals, model outputs, proposals and QA are persisted. Actual follow-up policy is available through the tools.

Python retains deterministic financial calculations, source matching, SQLite jobs, exact-version approval, channel/identity boundaries, simulated delivery, deduplication and scheduling. AI owns the commercial objective, alternatives, strategy and email. Operational warnings are retained, but reviewed support/order-status/channel actions can proceed when justified. A possible unassigned same-name record does not itself prohibit neutral support to an independently identified customer; actual identity conflicts still block outreach. No records are silently merged.

## Measured results

| Current portfolio disposition | Before | After |
|---|---:|---:|
| Pursue | 53 | 245 |
| Hold | 392 | 151 |
| No action | 41 | 90 |
| Current assessed records | 486 | 486 |

The live app contains 245 recovery drafts awaiting approval. These are account records, not a claim that all names represent independently verified institutions. The separate prospect record remains hidden from Phase 1. There are 284 specific pending verification tasks across 247 records, including 81 nonblocking tasks; task/account counts overlap with prepared outreach and must not be added as distinct customers. Remaining holds are dispositions with reasons, not failed executions.

All final proposals passed every required QA dimension at 4/5 or better: 465 passed without revision and 21 required one revision. An independent blind comparison using `gpt-6-astra` preferred the final result in all 28 representative cases. Production investigations/reviews use configurable `gpt-6.1-sol`, high reasoning. Mean old→new scores: evidence coverage 3.50→4.93; specificity 3.07→4.79; personalization 3.25→4.86; appropriateness 2.96→4.71; uncertainty 4.04→4.86; sales progression 2.68→4.82; factuality 4.18→4.96. Every final sample dimension scored at least 4. These are model judgments on a purposive sample, supplemented by direct inspection—not proof of revenue lift or portfolio-wide human review.

An initial comparison omitted necessary evidence and was discarded. Intermediate results were superseded by the final 28-case comparison. Billing interruptions and an actual distributor/training schema conflict were diagnosed and repaired; the final portfolio has no unresolved execution failures. A test fixture initially cancelled two future reminders; both were restored before the affected accounts were reassessed. Live reminders were never changed by these experiments.

## Concrete commercial improvements

- **Hawk County:** a night-shift refresher discussion replaces a generic inventory check. The proposal offers to scope topics/timing without promising free training or availability.
- **ID DOC – Lone Tree:** a focused purchasing-contact handoff includes an offer to summarize prior orders. In a real simulated-reply test, the agent retained the customer's 20-pack CL-FS10 request, new contact, direct channel and delivery month, asking only for the missing full ship-to address.
- **Juniper Hills:** training support proceeds alongside open order SO-104267. The agent no longer requires the salesperson to resolve every source row before a neutral support discussion.
- **Iron County Jail:** a mailroom/training-support discussion keeps Range Line involved. A real customer-reply test preserved the stated distributor route while progressing the training request; it did not seek sell-through records or bypass the distributor.
- **Cedar County / Elk Point:** existing unanswered outreach and future reminders are recognized; no parallel initial email or duplicate reminder is created.

## Execution, cache and measured cost

One asynchronous worker and SQLite WAL remain. Default concurrency is now 24, following successful tests at 15 and 24 and observed provider capacity (5,000 RPM / 1 million TPM headers). Adaptive throttling/backoff, short transactions, durable jobs and account-level exclusion remain. No Redis, Celery or extra server was introduced. The final phase completed 304 new assessments in 1,074 seconds (17.0/minute), reusing 182 current results. Across 495 successful attempts at concurrency 24, mean duration was 84.72 seconds; the earlier 39 at concurrency 15 averaged 94.90 seconds. These are different cohorts with different revision needs, not a controlled speedup claim. The older matched six-account scheduling benchmark remains historical in `agentic-workflows.md`.

Through the completed experiment audit: 3,441 returned responses, 25,835,929 input tokens, 2,510,011 output tokens, approximately **$62.29** in recorded API cost. This deduplicates copied database events and includes diagnostics, discarded evaluations, independent grading and isolated conversation tests. Portfolio experiments alone recorded $46.49. Twenty-five response records were unpriced; unreturned usage and later live briefing refreshes are additional uncertainty. These estimates are not an invoice, remaining balance or spending guarantee.

Missing/stale coverage is checked automatically, as are source-file changes. Cache validity includes engine version, source-row fingerprints, CRM/contact/channel data, correspondence and outcomes. Generated assessments/tasks do not invalidate themselves. Billing/auth failures pause new AI work globally, preserve the queue and allow local work; explicit retry resumes after access is restored. A current successful assessment resolves obsolete initial-investigation failures while retaining their history.

## Approval, response and edit behavior

Every send remains simulated and requires human approval of the exact saved version. Bulk decisions are atomic and duplicate-safe. Replies cancel inappropriate reminders, preserve quoted customer facts and produce a new unapproved response. Due follow-ups add a useful next step rather than repeat a question. Opt-outs stop outreach.

Guided revisions and replies use the shared evidence/QA process. Human autosaves remain immediate; edits to reviewed narrow-scope messages queue a debounced quality check. The agent must preserve the exact human text, cannot silently rewrite it, and cannot approve it. The edited draft stays visible while approval waits. Failed checks can be edited again or repaired using human guidance; newer edits cannot be overwritten by an older running job.

The live account view initially served an old production bundle and incorrectly showed the earlier blanket order-hold instruction. Restarting Next.js on the tested build corrected the runtime precedence; the API already supplied the new reviewable draft. Account summaries now use the commercial objective, with the full assessment available underneath.

## Validation and acceptance evidence

- **176 backend tests, 40 frontend tests, production build passed.** Worker-specific regression also passed after selecting concurrency 24.
- Real isolated tests covered individual/bulk exact approval, simulated delivery, duplicate rejection, customer quote requests, distributor training replies, guided revisions, unchanged-text manual-edit QA, stale approval rejection, opt-outs, useful follow-ups, outcome netting, restart persistence and baseline restoration.
- HTTP and authenticated MCP use the same service. The running server exposes 35 Phase 1 tools, including guided revisions; unauthenticated access returned 401. A real authenticated `get_account` call returned the final Juniper Hills engine/strategy. No prospecting tool is exposed and no external ChatGPT tunnel was configured.
- All 486 verified assessments were imported through normal persistence after a guarded preview and live backup. No live context or human draft had changed. Existing messages, outcomes, approvals, outbox rows and queued follow-ups were identical before/after import.
- Browser review verified the refreshed five-priority briefing, grouped support work, optional agent instructions, exact draft editor, Juniper Hills next action and complete portfolio coverage.
- Source totals remain $4,263,918.86 versus $3,673,722.48; historical decline $590,196.38; physical tests 1,037,600 versus 846,295. All four CSV checksums and the registered baseline checksum match. The 25 duplicate-looking excess rows remain unconfirmed and were not deleted; silently removing them would change the decline by $8,354.78.

## Reproduce and review

Use `scripts/resume_recovery_evaluation.py` only for the isolated evaluation database; it requires explicit API-ready confirmation and a recorded-cost ceiling. `evaluate_recovery_comparison.py` records independent comparisons. `promote_recovery_evaluation.py` defaults to preview, requires complete current coverage and stopped live services, backs up the session and skips changed human work. It grants no approvals and does not replace the baseline.

Detailed evidence: `runtime/overhaul/final_audit.json`, `portfolio_results.json`, `blind_evaluation_recovery-4.jsonl`, `e2e_results.json`, `positive_final_results.json`, `manual_edit_results.json`, `promotion_results.json`, `live_verification.json` and `live_http_mcp.json`.

Start the demonstration at Overview → training/product-support work → Juniper Hills or Hawk County. Inspect the recommendation and exact email; review Iron County for channel-aware support and Lone Tree for the contact handoff. Approvals remain the user's decision. The customer-reply and follow-up rehearsal evidence is in disposable databases; those tests did not consume live demo state. The original reset baseline remains intentionally historical, so resetting it will require the current engine to reassess stale records; the pre-import session is also backed up.

Phase 1 is ready for a credible supervised, simulated demonstration. Real contacts/relationship owners, ambiguous identities, current budgets, fulfillment status, authorized pricing, training availability and distributor restrictions still require genuine business evidence. No recovered revenue has been established. Later phases remain hidden, and interview rehearsal/submission are still the user's next steps.

The existing [Jola Technologies Case Study Notion page](https://app.notion.com/p/41387100147980d59a8bd0a88d331b8a) was updated and read back in the Northeastern University workspace: existing status rows and next steps corrected; a dated verified-overhaul record added; historical content preserved.
