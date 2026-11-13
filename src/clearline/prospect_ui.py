"""One small public-prospect vertical slice, using the shared sales controls."""
import json
import streamlit as st
from .prospects import seed_prospects
from .sales_ui import readable_time, sales_controls, status_label, workflow_summary


def source_links(ids, sources):
    return " · ".join(f"[{sid}]({sources[sid]['url']})" for sid in ids if sid in sources)


def prospect_panel(store, settings):
    st.caption("SWABTEK / REAL-WORLD PROSPECTING")
    st.title("Prospecting Agent")
    st.write("Research an institution, assess product fit and purchasing routes, then prepare a personalized introduction.")
    st.markdown("[1. Choose a prospect](#choose-prospect) → [2. Review research](#review-research) → [3. Approve outreach](#approve-outreach) → [4. Track results](#track-results)")
    st.caption("Real public institutions, separate from the fictional recovery accounts. Existing customer status, buying intent and budget are unverified.")
    st.header("1. Choose a prospect", anchor="choose-prospect")
    rows = store.rows("SELECT * FROM opportunities WHERE workflow='prospecting' AND active=1 ORDER BY json_extract(evidence,'$.profile.priority'),name")
    if not rows:
        if st.button("Load two researched public leads"):
            seed_prospects(store, settings.as_of)
            st.rerun()
        return
    selected = st.selectbox("Real prospect", rows, format_func=lambda r: f"{r['name']} · {status_label(r['status'])}")
    opp = store.opportunity(selected["id"])
    profile = opp["evidence"]["profile"]
    st.divider()
    st.header("2. Review research & qualification", anchor="review-research")
    st.markdown(f"**Selected institution: {opp['name']}**")
    can_analyze = workflow_summary(store, opp)
    st.markdown(f"[Official institution page]({profile['official_url']})")
    st.write("**Why investigate:** " + profile["selection_reason"])
    if can_analyze and st.button("Research prospect & prepare email", type="primary"):
        try:
            jid = store.queue_prospect(opp["id"])
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    research = opp["evidence"].get("research")
    if research:
        sources = {s["id"]: s for s in research["sources"]}
        with st.expander("Research findings & sources"):
            for fact in research["facts"]:
                st.markdown(f"{fact['statement']} {source_links(fact['source_ids'], sources)}")
            for sid, source in sources.items():
                st.markdown(f"**{sid} · [{source['title']}]({source['url']})**")
                st.caption(f"Publication date: {source['published_date'] or 'Unknown'} · {source['temporal_status'].replace('_',' ')} · Retrieved: {source['retrieved_at']}")
            for limit in research["limitations"]:
                st.write("• " + limit)
            for unknown in research["unknowns"]:
                st.write("**Unverified:** " + unknown)
        decisions = store.rows("SELECT details,created_at FROM events WHERE opportunity_id=? AND kind='agent_decision' ORDER BY id DESC LIMIT 1", (opp["id"],))
        if decisions:
            report = json.loads(decisions[0]["details"])
            with st.expander("Read the agent's qualification & sales approach", expanded=opp["status"] == "awaiting_approval"):
                st.caption(f"Analysis saved {readable_time(decisions[0]['created_at'])}. The status above shows the current next step.")
                st.write(f"**{report['decision'].capitalize()} · {report['qualification'].replace('_',' ')}:** {report['rationale']}")
                st.write("**Recommended route:** " + report["channel"].replace("_", " "))
                st.write("**Target role:** " + report["target_role"])
                st.write("**Action proposed at the time:** " + report["recommended_action"])
                for field, label in [("operational_need", "Operational need"), ("product_fit", "Product fit"), ("purchasing_process", "Purchasing process"), ("channel_reasoning", "Channel rationale")]:
                    finding = report[field]
                    st.markdown(f"**{label}:** {finding['statement']} {source_links(finding['source_ids'], sources)}")
                st.write("**Alternative:** " + report["alternative_route"])
                for hypothesis in report["hypotheses"]:
                    st.write("**Hypothesis:** " + hypothesis)
                for question in report["unresolved_questions"]:
                    st.write("• " + question)
    sales_controls(store, opp)
    with st.expander("Research limits"):
        st.caption("Research uses at most 6 web actions and 1 model response. Qualification uses at most 3 model turns. Each stage has a timeout; failures require explicit retry. Saved work is reused.")
