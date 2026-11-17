# Prospect pipeline rehearsal

The combined preview completed discovery, screening, research and outreach preparation on November 16, 2026. The reviewer ZIP contains this Wyoming demonstration and runs locally on port 3001. The author's protected ChatGPT rehearsal uses a separate database and tunnel.

## Rehearse the saved example without spending credits

1. Open [Overview](http://127.0.0.1:3001/) and select **New prospects**. **Investigate real prospects** has four institutions awaiting research. **Verify prospect purchasing details** includes the institution researched during acceptance.
2. Open [the Wyoming candidates](http://127.0.0.1:3001/screening?origin=real_web&state=WY). Select **Wyoming Medium Correctional Institution**. Review the screening factors, the official directory evidence and the comparison with fictional Clearline customers.
3. Select **Review saved outreach**. Read the purchase-route recommendation, the four sources and the version 1 email. The proposed conversation concerns how the institution evaluates presumptive material screening and who would handle procurement.
4. Follow **Verify contact and route** to see exactly what the salesperson needs to establish. Leave it unresolved during this rehearsal. To demonstrate an email already awaiting review, open [Pennsylvania DOC](http://127.0.0.1:3001/screening?candidate=2dc5f09907f6e34e3171).
5. For a **new paid run**, open **Discover prospects**, select a geography, category and maximum, then **Preview discovery**. Confirmation starts discovery only. Later, select up to three verified real institutions, choose **Research selected prospects**, and confirm the quoted scope. Reopening a saved report is free. Built-in correctional directories cover Wyoming and California. Other combinations require an official US government HTML directory.

## What changed

| Stage | Reused | Connected or added |
|---|---|---|
| Discovery | SQLite opportunities, source evidence, background jobs | An explicitly confirmed directory search, official identity verification, source timestamps and deduplication of real candidates |
| Screening | Fictional agency records, deterministic ranking, product-fit factors and historical customer comparisons | One searchable list, source labels, filtering, shortlist and hold decisions. A score alone starts no research or outreach |
| Research | Phase 4 research and qualification schemas, source checks, saved reports and commercial decision rules | One user-selected institution per investigation, bounded source retrieval and a separate persistent usage meter |
| Outreach | Versioned drafts, editing, exact human approval and simulated delivery | A discovered real prospect needs an explicitly verified intended recipient, role, permission and buying route before its current draft can be approved |

The dashboard and MCP call the same application services for candidate search, evidence, decisions, cost previews, recipient verification and exact-version draft approval. In a separate ChatGPT Web rehearsal, discovery, research and qualification completed for Avenal State Prison. The run retained four sources and one draft, with metered usage of $0.050427. Purchasing authorization was still required, and no outreach was approved or delivered. The California records remain in that separate rehearsal.

## Live acceptance record

Discovery job `42a42f897c39439e84277d4eee5a5236` confirmed five distinct facilities from the [Wyoming corrections directory](https://corrections.wyo.gov/facilities).

| Institution | Candidate ID |
|---|---|
| Wyoming Honor Conservation Camp | `99c39c00a1688456c1bb` |
| Wyoming Honor Farm | `0d7c19514681e1461878` |
| Wyoming Medium Correctional Institution | `7c5d24004cd2b5547dbb` |
| Wyoming State Penitentiary | `55975aac56f945bf7534` |
| Wyoming Women's Center | `9d998196e8374b96dc09` |

All five scored **66.12/100**. For the selected institution, product fit contributed 40, segment purchasing patterns 20.87, and available context 5.25. No verified comparable bed capacity was extracted, so scale contributed zero. The saved case evidence identified 23 named buyers in the segment and purchases of both relevant products. Fewer than five buyers had sufficiently clear records for a dollar benchmark.

The selected facility's official page describes an intake and assessment role. The research agent found a state procurement process and a plausible product application. The kit gives a presumptive, nonspecific result and requires confirmation. The records establish neither an unmet need nor the responsible buyer. The commercial decision was **pursue a discovery conversation**. A direct inquiry was proposed to establish technical fit and identify the proper purchasing route. All four sources were undated and were labeled as current context. Their content at the November 1 case cutoff remains unverified. [Institution](https://corrections.wyo.gov/facilities/wyoming-medium-correctional-institution) · [Manufacturer](https://swabtek.com/products/general-narcotics-test-kit) · [State purchasing](https://ai.wyo.gov/divisions/general-services/purchasing) · [Distribution program](https://swabtek.com/pages/partners)

| Saved result | Identifier |
|---|---|
| Research report/job | `e532e83990824d9cbf69033c8e295d4d` |
| Commercial qualification/job | `a11fc2cc38d44bbf98f6f9ab22693d36` |
| Draft v1, *WMCI screening workflow and evaluation route* | `38b62df3bed34e039c9255b8bb4eb019` |

| Combined preview | Before | After discovery | After qualification and restart |
|---|---:|---:|---:|
| All candidates | 2,602 | 2,607 | 2,607 |
| Fictional CSV / previously identified real / real discovered online | 2,600 / 2 / 0 | 2,600 / 2 / 5 | 2,600 / 2 / 5 |
| Real prospects awaiting research | 0 | 5 | 4 |
| Completed real research reports | 1 | 1 | 2 |
| Real prospects needing verification | 1 | 1 | 2 |
| Emails ready for approval | 1 | 1 | 1 |
| Prospects in conversation | 0 | 0 | 0 |

The **Inspect the latest discovery results** card appeared with five candidates. The selected institution then moved from the research list to verification. Pennsylvania DOC remained the single email ready for approval. The combined dashboard and MCP returned matching counts after restart.

## Cost and preservation

| Standard GPT-6.1 Sol request | Input tokens | Output tokens | Metered estimate |
|---|---:|---:|---:|
| Discovery | 2,590 | 241 | $0.008884 |
| Institutional research | 5,377 | 880 | $0.022241 |
| Commercial qualification and draft | 1,888 | 997 | $0.014689 |
| **Total** | **9,855** | **2,118** | **$0.045814** |

Three generation requests completed on their first attempt. Scoring had zero model calls. Source retrieval used direct HTTPS without a paid hosted search tool. The $1 prospect meter has $0.954186 remaining and zero outstanding reservations. Its estimates use returned token counts and standard rates, with conservative handling of missing cache details. The separate $2 conversation meter has $0.957541 remaining. [Provider rates](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

Both local production builds passed, along with 480 backend and 135 frontend tests. The live test exercised the dashboard controls, then reopened the selected candidate, its draft, Overview and Action Center after a page reload and a service restart. No outreach was approved or sent. All four source CSV hashes matched. The original rows checked in the combined database matched, including 486 customer accounts, existing drafts, approvals, conversations and original prospect research.

One separate change occurred in the conversation rehearsal during the baseline interval, before Wyoming discovery. Lone Tree draft v6 was superseded by seven saved edits, ending at v13. The original draft hash difference is fully explained by v6's change of status. The prospect workflow submitted no Lone Tree writes. Those concurrent edits were retained.
