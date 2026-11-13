"""Supporting views, separate from the agent workflows."""
import json
from datetime import datetime, timezone
import streamlit as st
from .sales_ui import readable_time


def activity_panel(store, settings):
    st.caption("MONITORING")
    st.title("Agent activity")
    st.write("Check background execution, investigate failures, and retry or cancel work.")
    @st.fragment(run_every="3s")
    def show_activity():
        health=store.rows("SELECT state,seen_at FROM worker_state WHERE id=1")
        if health:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(health[0]["seen_at"])).total_seconds()
            alive=health[0]["state"]!="stopped" and age<settings.timeout_seconds+30
            st.info(f"Worker: {health[0]['state'] if alive else 'not running / stale'} · Last update {health[0]['seen_at']} (UTC)")
        usage=[json.loads(r["details"]) for r in store.rows("SELECT details FROM events WHERE kind='model_usage'")]
        st.caption(f"Recorded model requests: {sum(x['requests'] for x in usage)} · Input tokens: {sum(x['input_tokens'] for x in usage):,} · Output tokens: {sum(x['output_tokens'] for x in usage):,}. Failed requests may have provider usage not returned to the app.")
        jobs = store.rows("SELECT id,kind,opportunity_id,status,due_at,error FROM jobs ORDER BY created_at DESC LIMIT 30")
        names = {r["id"]:r["name"] for r in store.rows("SELECT id,name FROM opportunities")}
        kinds = {"scan":"Scan purchases", "analyze":"Assess recovery", "followup":"Prepare follow-up", "deliver":"Simulate approved email", "prospect_research":"Research prospect", "prospect_qualify":"Qualify prospect"}
        st.subheader("Background tasks")
        st.caption("Queued tasks wait for the worker. Failed tasks need your review before retrying. Times are UTC.")
        st.dataframe([{"Task":kinds.get(j["kind"],j["kind"]), "Account":names.get(j["opportunity_id"],"All recovery accounts"), "Status":j["status"].replace("_"," ").capitalize(), "Scheduled for":readable_time(j["due_at"]), "Error":j["error"] or "—"} for j in jobs], width="stretch", hide_index=True)
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
        with st.expander("Detailed execution log"):
            st.dataframe(store.rows("SELECT created_at,kind,details FROM events ORDER BY id DESC LIMIT 40"),width="stretch")
    show_activity()


def outreach_panel(store):
    st.caption("MONITORING")
    st.title("Outreach history")
    st.info("Simulation only. These entries are not sent emails, customer responses, or achieved sales.")
    counts={r["kind"]:r["n"] for r in store.rows("SELECT kind,COUNT(DISTINCT opportunity_id) AS n FROM outcomes GROUP BY kind")}
    funnel=st.columns(5)
    for column,kind,label in zip(funnel,["qualified","reply","quote","order","lost"],["Qualified (demo)","Responded (demo)","Quoted (demo)","Ordered (demo)","Lost (demo)"]):
        column.metric(label,counts.get(kind,0))
    st.caption("Distinct accounts per recorded outcome; an account can appear in several stages. No subsequent customer revenue has been independently verified.")
    entries = store.rows("SELECT p.name,p.workflow,o.subject,o.body,o.created_at FROM outbox o JOIN opportunities p ON p.id=o.opportunity_id ORDER BY o.created_at DESC")
    if not entries:
        st.info("No simulated outreach yet. Approve an email from the Customer Recovery Agent or Prospecting Agent to begin.")
    for entry in entries:
        label = "Fictional recovery account" if entry["workflow"] == "recovery" else "Real public prospect"
        with st.expander(f"{entry['name']} · {entry['subject']}"):
            st.caption(f"{label} · Simulated {readable_time(entry['created_at'])}")
            st.text(entry["body"])
    with st.expander("Recorded demo outcomes"):
        outcomes = store.rows("SELECT p.name AS Account,p.workflow AS Workflow,o.kind AS Outcome,o.note AS Notes,o.reference AS Reference,o.amount_cents/100.0 AS 'Amount (USD)',o.provenance AS Provenance,o.created_at AS Recorded FROM outcomes o JOIN opportunities p ON p.id=o.opportunity_id ORDER BY o.created_at DESC")
        if outcomes:
            st.dataframe(outcomes, width="stretch", hide_index=True)
        else:
            st.caption("No responses or commercial outcomes have been recorded.")
