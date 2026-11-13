# Operational briefing and parallel execution

Implemented locally on November 12, 2026. No deployment or GitHub push.

## What changed

Overview now opens with **What needs your attention**, a compact AI-prioritized operational briefing. The financial cards, segments, accounting rules and historical comparisons remain unchanged.

The backend builds a trusted snapshot of current assessments, campaign readiness, exact pending drafts, prior deliveries/outcomes, contact gaps, evidence holds, follow-up schedules, recent investigation results and financial exposure. The real OpenAI Agents SDK call selects up to three priorities, their supported reasons, and one or two summary facts. Representative account assessments inform its prioritization.

The model deliberately selects validated fact/action/reason identifiers rather than authoring executable URLs or numerical claims. The backend renders their factual wording, account counts and associated historical decline. This preserves AI prioritization while preventing invented metrics, customer responses, unsupported forecasts or executable actions. No defensible recovery forecast exists, so none is shown.

Supported destinations:

- A specific campaign with pending messages expanded, before any approval.
- Contact verification, evidence holds, individual approvals, or unassessed accounts filtered by the same backend predicates used to calculate the briefing counts.
- Scheduled recovery follow-ups only, including their due times.
- Failed/blocked jobs in Agent Activity.

Generating or opening a briefing never approves, sends, or launches account outreach. Human approval remains bound to exact saved draft versions. All delivery is simulated.

Briefs, model selections and source snapshots persist in `operational_briefs`; prior `revenue_briefs` history remains intact. Reads never enqueue work. The worker checks for meaningful state changes every 15 seconds and coalesces queued snapshots. Unchanged state reuses the saved briefing. Obsolete recommendations are hidden immediately until refreshed; results that become obsolete during generation are not published. Failed generations do not trigger an unlimited refresh loop. Manual regeneration is available, with one active generation per snapshot.

## Concurrency audit and benchmark

The previous worker was already asynchronous. It started six investigations and could cautiously grow to twelve; the measured 30-account batch only reached seven. There was no database lock error, missing worker, provider throttling or blocking model call serializing the portfolio. The initial limit and ramp-up were the main throughput constraints for this batch.

The worker now starts at **15 independent investigations**, with `CLEARLINE_CONCURRENCY=15` and `CLEARLINE_MAX_CONCURRENCY=15`. Both remain configurable. Each account retains its own job, evidence, reasoning and outreach preparation dependencies. No redundant agents or infrastructure were introduced.

Same 30 saved cases, including 20 unheld cases and 10 held/high-value cases; same model and prompts, real API calls, isolated databases, no approval or delivery:

| Measure | Previous worker | Updated worker |
|---|---:|---:|
| Configured starting / maximum concurrency | 6 / 12 | 15 / 15 |
| Observed simultaneous investigations | 7 | 15 |
| Observed in-flight model requests | Not instrumented | 15 |
| Batch elapsed time | 144.90 s | 66.09 s |
| Completed recommendations per minute | 12.42 | 27.23 |
| Completed cases | 30 / 30 | 30 / 30 |
| Model requests | 72 | 72 |
| Input + output tokens | 137,038 | 136,412 |
| Estimated API cost | $0.3715 | $0.3628 |
| API errors / rate-limit errors | 0 / 0 | 0 / 0 |

Throughput improved **2.19×**. Both runs produced 20 contact-verification candidates and 10 evidence holds. This is a single matched workload, not a general performance guarantee. Timing and generated text can vary. The cost estimate excludes unavailable usage/tool fees and is not an invoice.

Returned provider limits were 5,000 requests and 1,000,000 tokens per minute, with substantial remaining headroom. No increase beyond 15 was needed to meet the requested target. The application does not assume these limits will remain constant.

Adaptive throttling halves capacity on temporary rate-limit/overload responses, honors provider retry delays and reset headers including project token limits, and adds jitter. Five persisted attempts, per-run timeouts and bounded agent turns prevent unattended retry/reasoning loops. SDK-level retries remain disabled to avoid nested retries. Billing/authentication failures require intervention. This follows [OpenAI's rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits).

SQLite WAL, atomic claims, same-account serialization, scan exclusivity, worker ownership, restart recovery and duplicate-action prevention remain in place. Agent Activity distinguishes investigations running, actual requests in flight, jobs ready to start, and jobs waiting for retry. It retains completion/failure counts, average duration, five-minute throughput, tokens, estimated cost and batch progress.

## Verification and limitations

- 77 backend tests passed, including grounded action validation, exact filtered queues, stale brief suppression, contact/outcome exclusions, stable caching, failure-loop prevention, retry bounds and fifteen-way execution.
- 14 frontend tests passed; production build and TypeScript checks passed. Browser checks confirmed the specific campaign opens with pending messages expanded, the contact queue contains 35 accounts, and the follow-up screen contains only the three scheduled follow-ups.
- Real AI briefing generation succeeded. It prioritized the prepared campaign, contact gaps and evidence verification; all links and metrics were validated against persisted state.
- Preservation audit: all 3 scans, 488 opportunity records (including 2 real prospects), 20 draft versions, 3 approvals, 3 simulated outbox records, the campaign and its 15 members, prospect research and all 5 sources are byte-for-byte unchanged at the row level. No new approval, outcome or delivery was recorded in the application database.
- Contact verification and evidence-hold resolution still require verified source information. The briefing does not manufacture contacts, clear holds or claim an autonomous verification capability that does not exist.
- The worker and computer must stay running for unattended execution. Current account assessments were already complete, so benchmarks used isolated copies instead of paying to overwrite the live portfolio's decisions.

Full local benchmark and preservation evidence is saved in the gitignored `runtime/operational-briefing-benchmark.json`. Benchmark databases are under `/tmp/clearline-parallel-audit`; they contain fictional case-study data and must not be uploaded.

## Sales-friendly next steps and grouped record checks

Updated November 12 after the sales workflow review. Briefing descriptions use plain language (for example, “We just need to know who handles purchasing”). “Review 392 evidence holds” is no longer offered as a sales task.

The read-only grouping found 392 eligible recovery records with unanswered data questions. Of these, 174 have a current purchasing signal and 218 do not. Records without a signal remain available in Account Intelligence and the explicit all-checks view; they are excluded from the grouped daily requests. Distributor bill-to aggregates are also excluded from the requests, because they overlap end-customer views.

The `/checks` screen prepares four internal requests from the current evidence:

| Request | Customer records | Records with no other check group |
|---|---:|---:|
| Confirm pending orders | 35 | 17 |
| Fill in missing purchase dates | 25 | 7 |
| Check purchases through distributors | 80 | 31 |
| Match customer names and locations | 112 | 54 |

Groups overlap; 252 group memberships represent 174 records. These counts are not independently verified institutions or recovery forecasts. The request order prioritizes straightforward order/date questions. Within each group, customers needing only that type of answer come first, followed by larger historical account declines. No dollar totals are presented for the batch request.

Each request has a suggested responsible team, concise copyable text, and a downloadable CSV containing actual assigned source rows, customer names/aliases, order references, other outstanding checks, and empty response/reference columns. The default customer preview shows five rows; the full list is in the download. For example, Juniper Hills is first in the pending-orders request and references order SO-104267. Pending-order exports contain only open rows; missing-date exports contain only undated rows. All assigned rows are bounded by the case cutoff. Source-file hashes are rechecked on every request, including when parsed data is cached; changed or missing sources disable exports. Spreadsheet-formula-like text is escaped in downloads.

Action Center replaces individual recovery data/agent holds with the grouped requests. Contact tasks, real-prospect questions and execution errors remain visible. Existing account histories and individual decisions remain accessible.

The request is **prepared, not sent or assigned**. There is no new email transport, automatic team notification, response importer or hold override. Someone with the source information must correct the original records; a recovery scan then updates evidence and reassesses affected customers. Copying or downloading never clears a hold or approves outreach.

Validation: 81 backend tests and 17 frontend tests passed; TypeScript/production build passed. The live API, proxied CSV download, overview and grouped-request page were checked. One real AI briefing refresh succeeded (4,853 reported tokens; estimated $0.01073). Preserved customer/scan/draft/approval/outbox/campaign/source rows matched the pre-restart audit exactly. The existing 18 approvals and simulated deliveries were already present in that audit; this change created none.
