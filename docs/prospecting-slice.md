# Real SwabTek prospecting vertical slice

This milestone adds one public-research-to-draft workflow to the existing application. It does
not implement broad prospect discovery, expansion/cross-selling, campaigns, or external sending.

## Shortlist and selection

| Institution | Why investigate | Important limitation | Priority |
| --- | --- | --- | --- |
| Pennsylvania Department of Corrections | A February 17, 2026 official report describes synthetic-cannabinoid paper in legal mail. Public procurement guidance provides a discovery route. | Existing customer status, current needs, product validation, budget, incumbent suppliers and an applicable contract are unknown. | Selected for the live workflow |
| Massachusetts Department of Correction | Official search results describe mail-related incidents and existing TruNarc equipment. | Full-page access returned HTTP 403 during initial research. Existing equipment may reduce the opportunity; date and procurement route need verification. | Retained as an unqualified alternative |

Sources: [Pennsylvania incident](https://www.pa.gov/agencies/cor/about-us/newsroom/newsroom/doc-investigation-uncovers-scheme-to-smuggle-synthetic-drugs-thr),
[Pennsylvania procurement](https://www.pa.gov/agencies/cor/about-us/offices-and-bureaus/bureau-of-administration),
[Massachusetts official release](https://www.mass.gov/news/massachusetts-department-of-correction-announces-latest-results-from-efforts-to-prevent-drugs-and-contraband-in-state-prisons).

The proposed fit is an evaluation of presumptive item/paper screening, not a claim that SwabTek
will detect every relevant compound or replace confirmation procedures. Manufacturer descriptions
are not independent performance validation. See the [General Narcotics product page](https://swabtek.com/products/general-narcotics-test-kit).

Pennsylvania's [mail guidance](https://www.pa.gov/agencies/cor/find-or-contact-inmate/mail-rules)
distinguishes outsourced correspondence, centralized publication screening and institution-level
legal mail. Smart Communications is a mail-service vendor; it is not established here as a SwabTek
distributor. The [manufacturer partnership page](https://swabtek.com/pages/partners) does not prove
an authorized distributor or contract serving this prospect. Direct discovery is a conversation
about needs and the authorized procurement route, not an assumption that fulfillment should be direct.

## Architecture and execution

1. Two explicitly curated public leads are seeded under `real:` identity keys. No CSV matching occurs.
2. A `prospect_research` job uses the existing OpenAI Agents SDK/model and hosted web research.
3. A validated research bundle, source URLs, reported publication dates, retrieval timestamps,
   limitations and evidence hash are saved in SQLite. Source URLs must appear in provider-returned
   search/citation metadata and belong to allowed domains. URL checks do not establish claim truth.
4. The same transaction queues `prospect_qualify`. This agent retrieves the persisted evidence
   through a real function tool, distinguishes facts from hypotheses, recommends a channel and
   drafts a role-addressed email. Hold/reject decisions are valid outcomes.
5. The existing version-bound approval, simulated outbox, one-follow-up limit, manual outcomes,
   cancellation and restart recovery are reused. A new prospect draft always awaits human approval.

The Streamlit **Real prospects** tab displays linked evidence, qualifications, channel reasoning,
unknowns and the shared sales controls. **Jobs & activity** contains model usage and failures.
Recovery scans only deactivate recovery records; they cannot overwrite real prospects.

## Bounds and provenance

- Research: one model response, at most six hosted web actions, 4,500 output tokens.
- Qualification: at most three model turns, 4,500 output tokens per call, no web tools.
- Each stage uses the existing configured timeout (120 seconds by default), with provider retries
  disabled. Failed jobs require deliberate retry; the UI never silently starts a paid retry.
- One research execution per prospect is reused; research is not rerun by page refresh or daily
  recovery scans. Automatic repeating prospect campaigns are not implemented.
- The business cutoff remains November 1, 2026. Later dated sources are rejected. Undated pages
  are explicitly current context, not proof of what was true at the cutoff. Reported publication
  dates and claims still need human verification. No independent historical archive was established.
- Public pages and notes are untrusted evidence. There are no tools for sending, buying, logging
  into procurement portals, or changing external records. Remote SDK tracing is disabled.
- Usage records are token/tool counts, not invoices. Exact account billing is not available locally.
  [Model pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
  [tool pricing](https://developers.openai.com/api/docs/pricing) can inform a labeled estimate.

## Run and review

```bash
.venv/bin/clearline prospects --research-first
.venv/bin/clearline worker
```

In the UI select **Real prospects → Pennsylvania Department of Corrections**. Review the source
dates and claims, product limitations, channel choice, unresolved questions and email. Edit and
save before approving. Approval permits only a simulated outbox entry. The real recipient and
authority to represent SwabTek have not been established; no commercial contact is authorized.

The acceptance report in ignored `runtime/prospecting_acceptance_report.json` records the actual
live result, usage, failures and remaining checks. The main database keeps its real draft awaiting
the user's decision. Automated tests use only small synthetic fixtures and mocked API boundaries.
