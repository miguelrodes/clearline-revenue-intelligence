# Phase 3 controlled integration

This branch combines the newer Phase 1–2 contact-clearance implementation (including its local cache fix) with the existing Phase 3 screening branch. It is a separate local preview; the stable branch and live demo database are not changed.

## Run the isolated preview

Use three terminals from this integration checkout. Reuse the original repository's installed Python environment and frontend dependencies. Replace the two environment-specific paths below with the original checkout's actual locations; do not paste credentials into a terminal command or chat.

```bash
# Terminal 1: API; defaults to this checkout's runtime/phase3/screening.sqlite3.
/path/to/original/.venv/bin/python scripts/screening_dev.py api \
  --enable-screening --port 8002 --env-file /path/to/original/.env

# Terminal 2: combined worker. No portfolio catch-up, scheduled scan, or Phase 4 research.
/path/to/original/.venv/bin/python scripts/screening_dev.py worker \
  --enable-screening --env-file /path/to/original/.env

# Terminal 3: production frontend, explicitly built for the isolated API.
cd frontend
CLEARLINE_API_ORIGIN=http://127.0.0.1:8002 npm run build -- --webpack
CLEARLINE_API_ORIGIN=http://127.0.0.1:8002 npm run start -- --port 3001
```

Open http://127.0.0.1:3001/screening. Port 3000 remains the stable demo. The API's local-origin checks already permit port 3001. Do not start this preview on an arbitrary frontend port without updating the permitted origins. The Next.js production build embeds its API rewrite; rebuild it with the isolated origin if changing backends.

The screening feature flag defaults to off. The isolated launcher sets it explicitly. Existing recovery, contact-clearance, real-world prospecting and authentication paths are retained.

The combined worker handles explicitly queued existing-customer assessments, preparation, replies, revisions, follow-ups, approved simulated deliveries and manual briefing refreshes, together with Phase 3 agency jobs. Its nonempty job allowlist excludes full recovery scans and Phase 4 research. `auto_brief=False` also disables source-change scans, portfolio coverage catch-up and automatic briefing generation; the allowlist prevents scheduler ticks. Starting the worker does not create jobs or invalidate saved assessments. Already-requested permitted jobs, including interrupted work, can resume. Explicit `agency_scan` jobs retain their existing deterministic Phase 3 behavior.

For acceptance tests, pass the same `--db-path runtime/acceptance/test.sqlite3` to both API and worker. Only resolved paths inside this checkout's `runtime/` directory are accepted. The selected database also holds that session's Phase 3 usage ledger, so isolated tests cannot write through to the preview ledger. Copy the full database, including its usage records; do not use isolated copies to reset or evade the agreed spending cap. Starting the ordinary worker can execute queued jobs; bounded paid acceptance runs should use the acceptance harness instead.

## Data and qualification

- `screening.py` retains the original source-row matching and relationship classifications.
- `screening_rank.py` adds a separate ranking table. Weights are 40% product/institution fit, 25% operational scale, 25% observed purchaser similarity and 10% context/completeness. Jail beds are used for custodial institutions; population served is a weaker jurisdiction-scale proxy for police/sheriff agencies. Other types receive no invented scale value. Positive values are log-scaled and capped at the segment's 95th percentile. Missing scale gets no points, and ties sort reproducibly by name and ID.
- Scores are discovery priorities, not purchasing probabilities, revenue estimates, or proof of need. Customer and identity conflicts exclude records from the eligible shortlist irrespective of score. Unknown distributor coverage stays visible.
- Ranking is separate from qualification evidence identity, so adding/recomputing scores does not invalidate unchanged reports. Existing schema-compatible qualification reports are retained under the same commercial decision contract. New verified facts, recorded replies and material sales progress change only that agency's context hash; simple send tracking and the agent's own logs do not cause reassessment loops. The qualifier reads the relevant activity history. Requests for a current report reuse it without another job.
- Qualification and its independent reviewer use fresh contexts with the same configured model, supplied evidence tools only, bounded turns and at most one revision. The reviewer can decline a high-ranked candidate. No hosted web tools are allowed for fictional agencies.

## Decisions, contacts and outreach

`agency_workflow` and `agency_activity` persist accept/hold/reject reasons, verification, history and simulated sales progress. Saving partial information does not trigger AI or clear all prerequisites. Rejected prospects are excluded from the default list and automatic shortlist selection; the rejected filter keeps them inspectable. Holds and activity invalidate obsolete pending work.

Outreach requires an accepted prospect, current independently accepted qualification, verified operational evidence, a verified recipient and role, explicit permission, and a checked purchasing route/relationship. It is a new relationship introduction, never inferred recovery of an existing buyer. A separate outreach agent and fresh reviewer prepare the exact draft. Drafts use the existing approval snapshots and simulated outbox, under a distinct `agency_screening` workflow. Both approval and delivery recheck context and prerequisites. A later edit to information or a hold revokes stale work. Delivery always goes to `simulation@example.invalid`; no real sending implementation was added.

Agency delivery uses its own worker kind. The combined worker also processes explicitly queued recovery deliveries and follow-ups, with the existing exact-version approval and duplicate-delivery checks. Agency activity history distinguishes simulated contact, replies and advancement from verified revenue. The Phase 4 real-world records never enter this agency workflow.

## Cost ceiling

`agency_usage` is a persistent incremental ledger: at most $5 estimated standard-tier model usage and 15 distinct additional agencies. Before every request, the HTTP hook atomically reserves a conservative input/output upper bound. It rejects unknown pricing, nonstandard service tiers, hosted tools, nontext inputs, server-side history, streaming, oversized payloads and unbounded output. Token usage settles reservations only after a known response; unknown or interrupted usage keeps the full reservation. Exhaustion stops dispatch and is not treated as a retryable provider failure. A per-job request limit includes retries. The default preview uses its existing ledger; explicit acceptance database copies retain copied usage and use their own ledger to avoid preview writes. The older Phase 3 validation scripts explicitly share the preview ledger and must not be used for tests requiring an unchanged preview database.

Costs are split into investigation, commercial review, qualification revision, outreach and outreach review as applicable. Prices are estimates from the existing dated local table, not an OpenAI invoice. This task does not grant permission to raise the limits or run another portfolio-wide assessment.

## Validation evidence

Local, ignored `runtime/phase3/` contains the original database snapshots, preservation manifests, ten-candidate shortlist, real qualification results, budget ledger, separate synthetic outreach-validation database, HTTP/MCP results and completion report. These contain case-study evidence and must not be committed or uploaded.

Checks: full backend suite, frontend tests, TypeScript, production build, authenticated MCP/runtime parity, unchanged assessment reuse, ranking reproducibility, partial verification, exact-version approval, stale authorization, rejection persistence, duplicate sending, shared cost ceiling and preservation of original business data. The real AI outreach-validation draft was left unapproved and unsent. Only automated fixtures exercise approval/simulated delivery.
