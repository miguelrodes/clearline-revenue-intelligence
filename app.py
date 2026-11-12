"""Streamlit is a control surface; the worker owns all agent execution."""
import json
import os
from datetime import datetime, timezone
import streamlit as st
from clearline.config import Settings
from clearline.store import Store, STOPPED_STATUSES
from clearline.sales_ui import sales_controls
from clearline.prospect_ui import prospect_panel

st.set_page_config(page_title="Clearline Revenue Intelligence",layout="wide")
settings = Settings.load()
store = Store(settings.db_path)
st.title("Revenue operations")
st.caption("Fictional recovery accounts and real public prospects stay separate · Human approval · Simulated outbox only")
if not os.getenv("OPENAI_API_KEY", "").strip():
    st.info("Data scans work now. Agent jobs require OPENAI_API_KEY in your local .env file; no synthetic AI output is generated.")
with st.sidebar:
    st.header("Controls")
    st.caption(f"Business as-of: {settings.as_of} · Model: {settings.model} · Reasoning: {settings.reasoning}")
    days = st.number_input("Inactivity minimum (days)",min_value=1,value=90)
    fraction = st.slider("Decline threshold (%)",5,90,25)
    analysis_limit = st.selectbox("New cases to analyze per scan",[0,1,2,3],index=1)
    if st.button("Run recovery scan",type="primary"):
        store.enqueue("scan",{"analysis_limit":analysis_limit,"policy":{"inactivity_days":days,"decline_fraction":fraction/100}})
        st.success("Queued for the background worker")
    if st.button("Enable daily scan"):
        store.schedule(analysis_limit=analysis_limit,policy={"inactivity_days":days,"decline_fraction":fraction/100})
        st.success("Enabled; keep the worker running")
    if st.button("Disable scheduled scan"):
        store.schedule(enabled=False)
    schedules=store.rows("SELECT enabled,next_run FROM schedules WHERE name='recovery_scan'")
    st.caption("Next scan (UTC): "+schedules[0]["next_run"] if schedules and schedules[0]["enabled"] else "Daily schedule is off")
    if st.button("Refresh results"): st.rerun()
    paused=store.paused()
    if st.button("Resume worker" if paused else "Pause new jobs"):
        store.set_paused(not paused)
        st.rerun()
    st.caption("Start the worker separately: clearline worker")

queue_tab,prospect_tab,activity_tab,outbox_tab = st.tabs(["Recovery queue","Real prospects","Jobs & activity","Simulated outbox"])
with queue_tab:
    scans = store.rows("SELECT summary,created_at FROM scans ORDER BY created_at DESC LIMIT 1")
    if scans:
        summary = json.loads(scans[0]["summary"])
        cols = st.columns(3)
        cols[0].metric("Fictional Clearline decline (Jan–Oct)",f"${(summary['prior_cents']-summary['current_cents'])/100:,.0f}")
        cols[1].metric("Recovery candidates requiring review",summary["opportunities"])
        cols[2].metric("No known blocking flags",summary["reviewable"])
        with st.expander("Scan provenance and data-quality limits"):
            st.json(summary)
    cases = store.rows("SELECT id,name,state,decline_cents,holds,status,evidence FROM opportunities WHERE active=1 AND workflow='recovery' ORDER BY decline_cents DESC")
    include_holds = st.checkbox("Include accounts held for identity/channel review")
    visible = [c for c in cases if include_holds or not json.loads(c["holds"])]
    signal=st.selectbox("Signal",["All","inactivity","reduced_purchasing","product_decline","direct_gap_channel_review"],format_func=lambda x:x.replace("_"," ").capitalize())
    if signal!="All": visible=[c for c in visible if signal in {s["type"] for s in json.loads(c["evidence"])["signals"]}]
    if visible:
        st.dataframe([{"Account":c["name"],"State":c["state"],"Historical decline":f"${c['decline_cents']/100:,.2f}","Status":c["status"].replace("_"," "),"Flags":", ".join(json.loads(c["holds"]))} for c in visible],width="stretch",hide_index=True)
        chosen = st.selectbox("Account",visible,format_func=lambda x:f"{x['name']} ({x['state']}) · {x['status']}")
        opp = store.opportunity(chosen["id"])
        st.write("Historical decline:",f"${opp['decline_cents']/100:,.2f}")
        e=opp["evidence"]
        st.caption(f"Owner: {e.get('owner') or 'Unassigned'} · Last identified purchase: {e.get('last_purchase','Unknown')}")
        a,b,c,d=st.columns(4)
        a.metric("Prior-period net purchases",f"${e.get('prior_cents',0)/100:,.2f}")
        b.metric("Current-period net purchases",f"${e.get('current_cents',0)/100:,.2f}")
        c.metric("Prior physical tests",f"{e.get('prior_tests',0):,}")
        d.metric("Current physical tests",f"{e.get('current_tests',0):,}")
        st.write("**Signals:** "+", ".join(dict.fromkeys(s["type"].replace("_"," ") for s in e["signals"])))
        if e.get("crm_notes"): st.write("**CRM note:** "+e["crm_notes"])
        st.caption("Aliases and untimestamped CRM notes require verification. Unknown distributor customers can conceal continued purchasing.")
        product_rows=[{"Product":p["name"],"Prior net":f"${p['prior_cents']/100:,.2f}","Current net":f"${p['current_cents']/100:,.2f}","Prior tests":p["prior_tests"],"Current tests":p["current_tests"],"Pack change at old list prices":f"${p['constant_list_value_change_cents']/100:,.2f}"} for p in e.get("products",[])]
        if product_rows: st.dataframe(product_rows,width="stretch",hide_index=True)
        if opp["holds"]: st.warning("Review required: "+", ".join(opp["holds"]))
        with st.expander("Identity, source rows and all evidence"): st.json(opp["evidence"])
        with st.expander("What-if restoration — assumptions, not a forecast"):
            share=st.slider("Assumed share of this historical decline restored (%)",0,100,25)
            scenario=round(opp["decline_cents"]*share/100)
            st.metric("Illustrative restored revenue",f"${scenario/100:,.2f}")
            st.caption("Historical decline × assumed restoration share. This is not a probability, forecast, or achieved revenue. It excludes account growth and avoids counting distributor sales again.")
            if st.checkbox("Apply an assumed gross margin"):
                margin=st.number_input("Assumed gross margin (%) — source data has no costs",min_value=0.0,max_value=100.0,value=0.0)
                st.metric("Illustrative gross profit",f"${scenario*margin/10000:,.2f}")
                st.caption("Before sales effort, model usage, and other operating costs. This is not EBITDA improvement.")
        if st.button("Ask recovery agent",disabled=bool(opp["holds"]) or opp["status"] in STOPPED_STATUSES):
            try:
                jid=store.queue_analysis(opp["id"])
                state=store.rows("SELECT status FROM jobs WHERE id=?",(jid,))[0]["status"]
                st.info(f"Analysis job: {state.replace('_',' ')}. Existing work is reused to avoid duplicate model calls. Inspect Jobs for details.")
            except ValueError as exc: st.error(str(exc))
        decisions=store.rows("SELECT details FROM events WHERE opportunity_id=? AND kind='agent_decision' ORDER BY id DESC LIMIT 1",(opp["id"],))
        if decisions:
            analysis=json.loads(decisions[0]["details"])
            st.subheader("Agent assessment")
            st.write(f"**{analysis['decision'].capitalize()}:** {analysis['rationale']}")
            st.write("**Recommended next action:** "+analysis["recommended_action"])
            with st.expander("Hypotheses and unresolved questions"):
                st.json({k:analysis[k] for k in ("hypotheses","evidence_fields","unresolved_questions")})
        sales_controls(store, opp)
    else: st.info("Run a scan using the background worker to populate the queue.")

with prospect_tab:
    prospect_panel(store, settings)

with activity_tab:
    @st.fragment(run_every="3s")
    def show_activity():
        health=store.rows("SELECT state,seen_at FROM worker_state WHERE id=1")
        if health:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(health[0]["seen_at"])).total_seconds()
            alive=health[0]["state"]!="stopped" and age<settings.timeout_seconds+30
            st.info(f"Worker: {health[0]['state'] if alive else 'not running / stale'} · Last update {health[0]['seen_at']} (UTC)")
        usage=[json.loads(r["details"]) for r in store.rows("SELECT details FROM events WHERE kind='model_usage'")]
        st.caption(f"Recorded model requests: {sum(x['requests'] for x in usage)} · Input tokens: {sum(x['input_tokens'] for x in usage):,} · Output tokens: {sum(x['output_tokens'] for x in usage):,}. Failed requests may have provider usage not returned to the app.")
        jobs = store.rows("SELECT id,kind,status,due_at,error FROM jobs ORDER BY created_at DESC LIMIT 30")
        st.dataframe(jobs,width="stretch")
        failed = [j for j in jobs if j["status"] in ("failed","blocked_config")]
        if failed:
            retry = st.selectbox("Retry after fixing the cause",failed,format_func=lambda j:f"{j['kind']} · {j['id'][:8]} · {j['status']}")
            if st.button("Retry selected job"):
                store.retry(retry["id"])
                st.rerun(scope="fragment")
        cancellable=[j for j in jobs if j["status"] in ("queued","running","blocked_config")]
        if cancellable:
            cancel=st.selectbox("Cancel work",cancellable,format_func=lambda j:f"{j['kind']} · {j['id'][:8]} · {j['status']}")
            if st.button("Cancel selected job"):
                store.cancel_job(cancel["id"])
                st.rerun(scope="fragment")
            st.caption("An in-flight API call may finish; a cancelled job cannot create a draft or action.")
        st.dataframe(store.rows("SELECT created_at,kind,details FROM events ORDER BY id DESC LIMIT 40"),width="stretch")
    show_activity()
with outbox_tab:
    st.info("Simulation only. These entries are not sent emails, customer responses, or achieved sales.")
    counts={r["kind"]:r["n"] for r in store.rows("SELECT kind,COUNT(DISTINCT opportunity_id) AS n FROM outcomes GROUP BY kind")}
    funnel=st.columns(5)
    for column,kind,label in zip(funnel,["qualified","reply","quote","order","lost"],["Qualified (demo)","Responded (demo)","Quoted (demo)","Ordered (demo)","Lost (demo)"]):
        column.metric(label,counts.get(kind,0))
    st.caption("Distinct accounts per recorded outcome; an account can appear in several stages. No subsequent customer revenue has been independently verified.")
    st.dataframe(store.rows("SELECT p.name,p.workflow,o.recipient,o.subject,o.body,o.delivery_mode,o.created_at FROM outbox o JOIN opportunities p ON p.id=o.opportunity_id ORDER BY o.created_at DESC"),width="stretch")
    st.dataframe(store.rows("SELECT p.name,p.workflow,o.kind,o.note,o.reference,o.amount_cents,o.provenance,o.created_at FROM outcomes o JOIN opportunities p ON p.id=o.opportunity_id ORDER BY o.created_at DESC"),width="stretch")
