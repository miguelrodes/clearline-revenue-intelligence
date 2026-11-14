# Phase 3 controlled integration

This branch combines the newer Phase 1–2 contact-clearance implementation (including its local cache fix) with the existing Phase 3 screening branch. It is a separate local preview; the stable branch and live demo database are not changed.

## Run the isolated preview

Use three terminals from this integration checkout. Reuse the original repository's installed Python environment and frontend dependencies. Replace the two environment-specific paths below with the original checkout's actual locations; do not paste credentials into a terminal command or chat.

```bash
# Terminal 1: API; the script always selects this checkout's runtime/phase3/screening.sqlite3.
/path/to/original/.venv/bin/python scripts/screening_dev.py api \
  --enable-screening --port 8002 --env-file /path/to/original/.env

# Terminal 2: agency-only worker. No recovery auto-coverage, scheduled scan, or Phase 4 research.
/path/to/original/.venv/bin/python scripts/screening_dev.py worker \
  --enable-screening --env-file /path/to/original/.env

# Terminal 3: production frontend, explicitly built for the isolated API.
cd frontend
CLEARLINE_API_ORIGIN=http://127.0.0.1:8002 npm run build -- --webpack
CLEARLINE_API_ORIGIN=http://127.0.0.1:8002 npm run start -- --port 3001
```

Open http://127.0.0.1:3001/screening. Port 3000 remains the stable demo. The API's local-origin checks already permit port 3001. Do not start this preview on an arbitrary frontend port without updating the permitted origins. The Next.js production build embeds its API rewrite; rebuild it with the isolated origin if changing backends.

The screening feature flag defaults to off. The isolated launcher sets it explicitly. Existing recovery, contact-clearance, real-world prospecting and authentication paths are retained.

## Data and qualification

- `screening.py` retains the original source-row matching and relationship classifications.
- `screening_rank.py` adds a separate ranking table. Weights are 40% product/institution fit, 25% operational scale, 25% observed purchaser similarity and 10% context/completeness. Jail beds are used for custodial institutions; population served is a weaker jurisdiction-scale proxy for police/sheriff agencies. Other types receive no invented scale value. Positive values are log-scaled and capped at the segment's 95th percentile. Missing scale gets no points, and ties sort reproducibly by name and ID.
- Scores are discovery priorities, not purchasing probabilities, revenue estimates, or proof of need. Customer and identity conflicts exclude records from the eligible shortlist irrespective of score. Unknown distributor coverage stays visible.
- Ranking is separate from qualification evidence identity, so adding/recomputing scores does not invalidate unchanged reports. Existing schema-compatible qualification reports are retained under the same commercial decision contract. New verified facts, recorded replies and material sales progress change only that agency's context hash; simple send tracking and the agent's own logs do not cause reassessment loops. The qualifier reads the relevant activity history. Requests for a current report reuse it without another job.
- Qualification and its independent reviewer use fresh contexts with the same configured model, supplied evidence tools only, bounded turns and at most one revision. The reviewer can decline a high-ranked candidate. No hosted web tools are allowed for fictional agencies.

## Decisions, contacts and outreach

`agency_workflow` and `agency_activity` persist accept/hold/reject reasons, verification, history and simulated sales progress. Saving partial information does not trigger AI or clear all prerequisites. Rejected prospects are excluded from the default list and automatic shortlist selection; the rejected filter keeps them inspectable. Holds and activity invalidate obsolete pending work.

Outreach requires an accepted prospect, current independently accepted qualification, verified operational evidence, a verified recipient and role, explicit permission, and a checked purchasing route/relationship. It is a new relationship introduction, never inferred recovery of an existing buyer. A separate outreach agent and fresh reviewer prepare the exact draft. Drafts use the existing approval snapshots and simulated outbox, under a distinct `agency_screening` workflow. Both approval and delivery recheck context and prerequisites. A later edit to information or a hold revokes stale work. Delivery always goes to `simulation@example.invalid`; no real sending implementation was added.

Agency delivery uses its own worker kind, so the isolated worker cannot consume copied recovery deliveries or follow-ups. Its activity history distinguishes simulated contact, replies and advancement from verified revenue. The Phase 4 real-world records never enter this agency workflow.

## Cost ceiling

`agency_usage` is a persistent incremental ledger: at most $5 estimated standard-tier model usage and 15 distinct additional agencies. Before every request, the HTTP hook atomically reserves a conservative input/output upper bound. It rejects unknown pricing, nonstandard service tiers, hosted tools, nontext inputs, server-side history, streaming, oversized payloads and unbounded output. Token usage settles reservations only after a known response; unknown or interrupted usage keeps the full reservation. Exhaustion stops dispatch and is not treated as a retryable provider failure. A per-job request limit includes retries. Validation database copies share the preview ledger rather than resetting the allowance.

Costs are split into investigation, commercial review, qualification revision, outreach and outreach review as applicable. Prices are estimates from the existing dated local table, not an OpenAI invoice. This task does not grant permission to raise the limits or run another portfolio-wide assessment.

## Validation evidence

Local, ignored `runtime/phase3/` contains the original database snapshots, preservation manifests, ten-candidate shortlist, real qualification results, budget ledger, separate synthetic outreach-validation database, HTTP/MCP results and completion report. These contain case-study evidence and must not be committed or uploaded.

Checks: full backend suite, frontend tests, TypeScript, production build, authenticated MCP/runtime parity, unchanged assessment reuse, ranking reproducibility, partial verification, exact-version approval, stale authorization, rejection persistence, duplicate sending, shared cost ceiling and preservation of original business data. The real AI outreach-validation draft was left unapproved and unsent. Only automated fixtures exercise approval/simulated delivery.
