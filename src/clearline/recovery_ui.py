"""Account-first recovery review, with supporting evidence progressively disclosed."""
import json

import streamlit as st

from .sales_ui import readable_time, sales_controls, status_label, workflow_summary


SIGNALS = {
    "inactivity": "No recent purchases",
    "reduced_purchasing": "Buying less overall",
    "product_decline": "Buying less of a product",
    "direct_gap_channel_review": "Possible distributor switch",
}
HOLDS = {
    "ambiguous_identity": "More than one possible account match",
    "undated_history": "Some purchase dates are missing",
    "open_orders_require_review": "Open orders need checking",
    "known_distributor_channel": "Known distributor purchasing needs reconciliation",
    "possible_missing_state_alias": "An account alias has no state",
    "multiple_shipping_cities": "Purchases span multiple shipping cities",
    "identity_needs_review": "Account identity needs verification",
}


def recovery_panel(store, settings):
    st.caption("CLEARLINE REVENUE INTELLIGENCE / PHASE 1")
    st.title("Customer Recovery Agent")
    st.write("Find customers who stopped buying or are buying less, then turn the evidence into a recovery conversation.")
    st.markdown("[1. Find opportunities](#find-opportunities) → [2. Review an account](#review-account) → [3. Approve outreach](#approve-outreach) → [4. Track results](#track-results)")

    st.header("1. Find recovery opportunities", anchor="find-opportunities")
    st.caption("The scan compares purchase history and flags inactivity, reduced purchasing, and product-level declines.")
    with st.expander("Scan rules & daily automation"):
        days = st.number_input("Days without a purchase before flagging", min_value=1, value=90)
        fraction = st.slider("Minimum purchasing decline (%)", 5, 90, 25)
        analysis_limit = st.selectbox("Accounts the AI can analyze per scan", [0, 1, 2, 3], index=1)
        st.caption("Choose 0 to scan purchase history without AI analysis.")
        schedules = store.rows("SELECT enabled,next_run FROM schedules WHERE name='recovery_scan'")
        enabled = bool(schedules and schedules[0]["enabled"])
        st.caption("Next daily scan: " + readable_time(schedules[0]["next_run"]) if enabled else "Daily scanning is off")
        if st.button("Turn off daily scanning" if enabled else "Turn on daily scanning"):
            store.schedule(enabled=not enabled, analysis_limit=analysis_limit, policy={"inactivity_days":days,"decline_fraction":fraction/100})
            st.rerun()
        st.caption("Scheduled scans use these limits. Keep the worker running and the computer awake.")
    if st.button("Run recovery scan", type="primary"):
        store.enqueue("scan", {"analysis_limit":analysis_limit,"policy":{"inactivity_days":days,"decline_fraction":fraction/100}})
        st.success("Scan queued. Refresh results after the background worker finishes.")
    st.caption(f"Scans the supplied history and queues up to {analysis_limit} new AI assessments. Already scanned? Continue to step 2.")
    scans = store.rows("SELECT summary,created_at FROM scans ORDER BY created_at DESC LIMIT 1")
    if scans:
        summary = json.loads(scans[0]["summary"])
        with st.expander("Portfolio overview & scan details"):
            if "prior_cents" in summary:
                cols = st.columns(3)
                cols[0].metric("Historical revenue decline", f"${(summary['prior_cents']-summary['current_cents'])/100:,.0f}")
                cols[1].metric("Accounts flagged", summary["opportunities"])
                cols[2].metric("Without known data holds", summary["reviewable"])
            st.write("Comparable periods include credits and physical test volumes. Open orders and undated lines are excluded from the period comparison. Distributor sales are counted once; unknown end customers can conceal continued purchasing.")
            st.caption("Fictional Clearline case-study data · January–October 2025 vs. 2026 · Historical decline is not promised recovery.")
            st.caption(f"Business cutoff: {settings.as_of} · Last scan: {readable_time(scans[0]['created_at'])}")
            with st.expander("Full scan audit"):
                st.json(summary)

    cases = store.rows("SELECT id,name,state,decline_cents,holds,status,evidence FROM opportunities WHERE active=1 AND workflow='recovery' ORDER BY decline_cents DESC")
    if not cases:
        st.info("No saved opportunities yet. Run the recovery scan above, then refresh when it finishes.")
        return

    st.divider()
    st.header("2. Review an account", anchor="review-account")
    st.caption("Choose a flagged account. Review the purchase evidence and let the agent recommend the next action.")
    with st.expander("Filter accounts"):
        include_holds = st.checkbox("Include accounts held for identity/channel review")
        signal = st.selectbox("Reason flagged", ["All", *SIGNALS], format_func=lambda x: SIGNALS.get(x, x))
        approval_only = st.checkbox("Only show emails needing my approval")
    visible = [c for c in cases if include_holds or not json.loads(c["holds"])]
    if signal != "All":
        visible = [c for c in visible if signal in {s["type"] for s in json.loads(c["evidence"])["signals"]}]
    if approval_only:
        visible = [c for c in visible if c["status"] == "awaiting_approval"]
    if not visible:
        st.info("No accounts match these filters. Open Filter accounts to broaden the selection.")
        return
    chosen = st.selectbox("Account", visible, format_func=lambda x: f"{x['name']} ({x['state']}) · {status_label(x['status'])}")
    st.caption(f"{len(visible)} accounts shown, ordered by historical revenue decline. Use Filter accounts to include held accounts or find emails awaiting approval.")
    with st.expander("Compare accounts"):
        st.dataframe([{"Account": c["name"], "State": c["state"], "Historical decline": f"${c['decline_cents']/100:,.2f}", "Current stage": status_label(c["status"]), "Review needed": "; ".join(HOLDS.get(h, h.replace('_', ' ')) for h in json.loads(c["holds"]))} for c in visible], width="stretch", hide_index=True)

    opp = store.opportunity(chosen["id"])
    e = opp["evidence"]
    st.markdown(f"**Selected account: {opp['name']}**")
    st.caption(f"{opp['state']} · Account owner: {e.get('owner') or 'Unassigned'} · Fictional case-study account")
    can_analyze = workflow_summary(store, opp)

    st.markdown("**Why it was flagged**")
    st.write(" · ".join(dict.fromkeys(SIGNALS.get(s["type"], s["type"].replace('_', ' ')) for s in e["signals"])))
    a, b = st.columns(2)
    a.metric("Revenue decline", f"${opp['decline_cents']/100:,.0f}")
    b.metric("Physical tests purchased", f"{e.get('current_tests', 0):,}", delta=f"{e.get('current_tests', 0)-e.get('prior_tests', 0):+,} vs. prior period", delta_color="off")
    st.caption(f"January–October purchases: ${e.get('prior_cents', 0)/100:,.0f} in 2025 → ${e.get('current_cents', 0)/100:,.0f} in 2026. Last identified purchase: {e.get('last_purchase', 'Unknown')}.")
    if e.get("crm_notes"):
        st.write("**CRM context:** " + e["crm_notes"])
    st.caption("The CRM note and account match need verification. No direct orders does not prove that a customer stopped buying through distributors.")
    if opp["holds"]:
        for hold in opp["holds"]:
            st.warning(HOLDS.get(hold, hold.replace("_", " ")))

    if can_analyze:
        if st.button("Analyze account & prepare email", type="primary"):
            try:
                store.queue_analysis(opp["id"])
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        st.caption("The agent reviews saved evidence, explains its recommendation and drafts an email only if appropriate. This uses the configured AI API.")

    decisions = store.rows("SELECT details,created_at FROM events WHERE opportunity_id=? AND kind='agent_decision' ORDER BY id DESC LIMIT 1", (opp["id"],))
    if decisions:
        analysis = json.loads(decisions[0]["details"])
        with st.expander("Read the agent's saved assessment", expanded=opp["status"] == "agent_held"):
            st.caption(f"Saved {readable_time(decisions[0]['created_at'])}. This is an analysis snapshot; the status above shows what has happened since.")
            st.write("**Assessment:** " + analysis["rationale"])
            st.write("**Action proposed at the time:** " + analysis["recommended_action"])
            for question in analysis["unresolved_questions"]:
                st.write("• " + question)
            with st.expander("Hypotheses and evidence references"):
                st.json({k: analysis[k] for k in ("hypotheses", "evidence_fields")})

    with st.expander("Purchase breakdown & source evidence"):
        st.caption("Prior period: January–October 2025. Current period: January–October 2026. Training is excluded from physical test counts.")
        products = [{"Product": p["name"], "2025 revenue": f"${p['prior_cents']/100:,.2f}", "2026 revenue": f"${p['current_cents']/100:,.2f}", "2025 tests": p["prior_tests"], "2026 tests": p["current_tests"], "Pack change at old list prices": f"${p['constant_list_value_change_cents']/100:,.2f}"} for p in e.get("products", [])]
        if products:
            st.dataframe(products, width="stretch", hide_index=True)
        st.json(e)
    with st.expander("Explore a recovery scenario (optional)"):
        share = st.slider("Assumed share of this historical decline restored (%)", 0, 100, 25)
        scenario = round(opp["decline_cents"] * share / 100)
        st.metric("Illustrative restored revenue", f"${scenario/100:,.2f}")
        st.caption("Historical decline × your assumption. This is not a probability, forecast or achieved revenue; it excludes growth and avoids double-counting distributor sales.")
        if st.checkbox("Apply an assumed gross margin"):
            margin = st.number_input("Assumed gross margin (%) — source data has no costs", min_value=0.0, max_value=100.0, value=0.0)
            st.metric("Illustrative gross profit", f"${scenario*margin/10000:,.2f}")
            st.caption("Before sales effort, model usage and operating costs. This is not EBITDA improvement.")

    sales_controls(store, opp)
