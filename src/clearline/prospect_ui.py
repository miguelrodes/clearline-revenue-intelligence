"""One small public-prospect vertical slice, using the shared sales controls."""
import json
import streamlit as st
from .prospects import seed_prospects
from .sales_ui import sales_controls
from .store import STOPPED_STATUSES


def source_links(ids, sources):
    return " · ".join(f"[{sid}]({sources[sid]['url']})" for sid in ids if sid in sources)


def prospect_panel(store, settings):
    st.subheader("Real SwabTek prospects")
    st.info("Publicly identified institutions. Their customer status, buying intent and budget are unknown. These records are never matched to fictional Clearline accounts.")
    rows = store.rows("SELECT * FROM opportunities WHERE workflow='prospecting' AND active=1 ORDER BY json_extract(evidence,'$.profile.priority'),name")
    if not rows:
        if st.button("Load two researched public leads"):
            seed_prospects(store, settings.as_of)
            st.rerun()
        return
    st.dataframe([{"Institution": r["name"], "State": r["state"], "Status": r["status"].replace("_", " ")} for r in rows], width="stretch", hide_index=True)
    selected = st.selectbox("Real prospect", rows, format_func=lambda r: r["name"])
    opp = store.opportunity(selected["id"])
    profile = opp["evidence"]["profile"]
    st.markdown(f"[Official institution page]({profile['official_url']})")
    st.write("**Why investigate:** " + profile["selection_reason"])
    st.caption("Research: at most 6 hosted web actions and 1 model response. Qualification: at most 3 model turns. Each stage has a timeout; failures require explicit retry. Existing completed work is reused.")
    if st.button("Research and qualify prospect", disabled=opp["status"] in STOPPED_STATUSES):
        try:
            jid = store.queue_prospect(opp["id"])
            status = store.rows("SELECT status FROM jobs WHERE id=?", (jid,))[0]["status"]
            st.info(f"Research job: {status}. The worker will save sources, qualify the prospect and prepare a draft. Use Refresh results to see progress.")
        except ValueError as exc:
            st.error(str(exc))
    research = opp["evidence"].get("research")
    if research:
        sources = {s["id"]: s for s in research["sources"]}
        st.subheader("Research evidence")
        for fact in research["facts"]:
            st.markdown(f"{fact['statement']} {source_links(fact['source_ids'], sources)}")
        with st.expander("Sources, dates and evidence limitations"):
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
            st.subheader("Qualification and sales approach")
            st.write(f"**{report['decision'].capitalize()} · {report['qualification'].replace('_',' ')}:** {report['rationale']}")
            for field, label in [("operational_need", "Operational need"), ("product_fit", "Product fit"), ("purchasing_process", "Purchasing process"), ("channel_reasoning", "Channel rationale")]:
                finding = report[field]
                st.markdown(f"**{label}:** {finding['statement']} {source_links(finding['source_ids'], sources)}")
            st.write("**Recommended route:** " + report["channel"].replace("_", " "))
            st.write("**Alternative:** " + report["alternative_route"])
            st.write("**Target role:** " + report["target_role"])
            st.write("**Next action:** " + report["recommended_action"])
            with st.expander("Hypotheses and questions to validate"):
                for hypothesis in report["hypotheses"]:
                    st.write("**Hypothesis:** " + hypothesis)
                for question in report["unresolved_questions"]:
                    st.write("• " + question)
    sales_controls(store, opp)
