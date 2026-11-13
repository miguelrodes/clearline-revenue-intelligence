# Phase 3 isolated review — November 13, 2026

The stable Phase 1–2 checkpoint is `31004a75885c322764bb8d7a2c4cf0cbe26dd0f3`
on `codex/phase1-foundation`, in `/Users/miguelrodes/Code/clearline-revenue-intelligence`.
It remains runnable at http://127.0.0.1:3000. The new work is separate, unmerged and unpushed:
`codex/phase3-prospect-screening`, `/Users/miguelrodes/Code/clearline-phase3`.

## Stable acceptance gate

All nine commercial categories are implemented and tested. All 486 records and 1,057 signals
have current dispositions: 252 human verification, 83 internal investigation, 11 monitoring,
140 no action. Zero source-account external actions are eligible because recipient/relationship
authorization is missing. That limitation is retained, not replaced by a simulation address.
The prior 44-case balanced evaluation passed 44/44 expected interventions; the eight named
regressions also passed. Independent means fresh context, not a different model family.

The stable rerun passed 277 backend and 46 frontend tests. The unchanged production build,
real-model conversation/approval/follow-up/reset exercise, authenticated 38-tool MCP test,
financial reconciliation and original activity preservation are recorded in
`docs/phase12-checkpoint.json` and private `runtime/commercial-v5/` artifacts.
The external ChatGPT tunnel is still not verified. No original demo reset was needed overnight.

## Screening and qualification

All 2,600 supplied fictional agency records are deterministically screened and persisted:

| Classification | Records |
| --- | ---: |
| Exact normalized direct-buyer match | 220 |
| Possible existing customer / channel association | 371 |
| Ambiguous identity | 166 |
| Unverified prospect | 1,843 |
| Unsupported institution type | 0 |

There were no identical source duplicates. Canonical collisions remain separate ambiguous
records. Existing-customer identification is evidence from fictional exports, not externally
verified institutional identity. Unknown distributor customers are never allocated or searched
on the web. CRM presence, aliases, open orders and named distributor history do not prove a
new buyer. Source rows and hashes accompany every record.

Priority tiers distinguish plausible custodial screening, other potential physical screening,
weakly established applications, unresolved identities and exclusions. Reviewed discovery
priorities appear first; ties use institution name. These are workload tiers, not probabilities,
revenue forecasts or claims of purchasing intent. Size, HIDTA and fiscal year-end do not create
purchasing deadlines or demand assumptions.

A separate prospect decision contract uses source retrieval, qualification and a fresh-context
commercial supervisor. It can qualify for internal discovery, investigate, require verification,
defer or reject. Tools retrieve agency attributes, all matching relationship pages, the actual
catalogue and observed segment purchasing. There is no web tool, email writer, approval or
sending action in this workflow. Critical review failures stay unresolved and cannot qualify.

Seventeen real AI workflows completed: nine discovery priorities, two investigations, four
human-verification decisions and two rejections. The other 2,583 agencies are screened but
**not AI-qualified**. A button can queue at most ten more promising unassessed candidates;
it does not keep expanding the batch automatically.

Review these examples:

- **AZ State Correctional Facility – Antelope Wells:** browser-triggered qualification,
  then real async worker execution, review and persistence. Plausible mail/material and surface
  screening, with actual need and customer/channel status explicitly unknown.
- **Crystal Lake Regional Logistics Hub (Security), KS:** excluded from the new-prospect
  shortlist because direct purchasing already exists. The evidence routes it to existing-account
  work; it does not reject the customer or fabricate dissatisfaction.
- **Natrona County Adult Probation:** further investigation because physical-screening fit
  cannot be inferred from a population associated with drug testing. No clinical-testing claim.
- **Albany Co Sheriff:** human reconciliation of conflicting identity records before prospect
  qualification. Existing order attribution is not silently merged.

## Verification and limitations

- Final suite: 301 backend tests, 50 frontend tests, production Webpack build passed.
- Live API and authenticated MCP: 42 tools in explicitly enabled review mode, 38 with the
  feature disabled. Unauthenticated MCP returns 401. Search, filters, pagination, detail,
  qualified/rejected reports and exact-evidence queue idempotence work through the API.
- Browser: search, detail, actual qualification trigger, saved result, rejection filter and
  rejected detail verified. No additional draft, approval, send, outcome or real-prospect record
  was created or changed. The isolated worker only claims screening jobs; a parallel execution
  regression proves it leaves recovery jobs untouched.
- Sixteen stratified cases used predeclared acceptable interventions: 16/16 agreement.
  A separate fresh-context evaluator scored factuality 4.94/5 and other dimensions 5/5 after
  complete-evidence review. This small same-model-family sample is **not proof of commercial
  accuracy, demand or sales impact**. Manual inspection confirmed cited records and the
  representative qualified, rejected and ambiguous cases.
- Retained failures: an initially ambiguous `critical_findings` schema caused three otherwise
  accepted reports to be held. Clarified schema now requires blocking errors only; no gate was
  relaxed. Four audit objections arose from omitted retrieval logs or the supplied record ID;
  complete-evidence reevaluation resolved them without changing the qualification decisions.
  All original artifacts remain available, including interrupted attempts. No unresolved critical
  errors remain in the evaluated sample.
- This run recorded 118 provider responses, 282,186 input and 62,271 output tokens, estimated
  **$1.0574051** including initial attempts and audit corrections. Prices are the existing telemetry
  estimates, not an invoice; interrupted calls without returned usage can be undercounted.
- Verified customer need, contacts, relationship permission and actual operational requirements
  remain unavailable. No new institution is proven net-new or ready to buy. The supplied dataset
  has no obviously unrelated institution types; unsupported-type rejection is covered by fixtures.

Private evidence and review baseline: `runtime/phase3/acceptance.json`, `evaluation.json`,
`evaluation-manifest.json`, `evaluations/`, `evaluations-first-schema/`,
`complete-evidence-audit.json`, `http-mcp-verification.json`, test/build logs and
`review-baseline.sqlite3`. None is tracked or pushed. Original CSV SHA-256 hashes and the
stable registered reset baseline match the checkpoint; original recovery/real-prospect tables
also match the isolated copy exactly. Financial totals remain $4,263,918.86 versus
$3,673,722.48, a $590,196.38 decline.

## Launch after review

The feature defaults **off**. It was enabled only in the separate local test instance and is
returned to disabled for handoff. No feature is merged into the stable demo. To enable the
isolated preview explicitly, stop its disabled API if it is running, then use three terminals:

```bash
cd /Users/miguelrodes/Code/clearline-phase3
/Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/screening_dev.py api --enable-screening --env-file /Users/miguelrodes/Code/clearline-revenue-intelligence/.env
```

```bash
cd /Users/miguelrodes/Code/clearline-phase3
/Users/miguelrodes/Code/clearline-revenue-intelligence/.venv/bin/python scripts/screening_dev.py worker --enable-screening --env-file /Users/miguelrodes/Code/clearline-revenue-intelligence/.env
```

```bash
cd /Users/miguelrodes/Code/clearline-phase3
# The verified build already uses port 8001. Rebuild after frontend changes:
CLEARLINE_API_ORIGIN=http://127.0.0.1:8001 npm run build --prefix frontend -- --webpack
npm run start --prefix frontend -- --port 3001
```

Open http://127.0.0.1:3001/screening. Filter qualification to **Prioritized for discovery** or
**Excluded from shortlist**, inspect the examples above, then review the six investigation /
verification cases. `CLEARLINE_SCREENING_ENABLED=1` is the equivalent backend feature flag
for the generic app entry point; the isolated launcher requires `--enable-screening` explicitly.
It always uses its own `runtime/phase3/screening.sqlite3` regardless of the stable `.env` DB path.
The existing installed dependencies are reused locally; no credentials or source CSVs were copied
into Git. Do not point the stable demo reset command at this directory.

The stable app remains the interview baseline. Decide whether the Phase 3 discovery criteria and
next tasks warrant integration before enabling or merging anything into it.
