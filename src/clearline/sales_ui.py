"""Shared human review and simulated action controls for both workflows."""
from datetime import datetime
import streamlit as st
from .data import cents
from .store import STOPPED_STATUSES


STATUS_LABELS = {
    "needs_review": "Ready for analysis", "needs_research": "Ready for research",
    "researched": "Research saved", "awaiting_approval": "Needs your approval",
    "approved": "Approved · simulation pending", "awaiting_response": "Outreach simulated",
    "agent_held": "Needs investigation", "rejected": "Not proceeding",
    "replied": "Reply recorded (demo)", "qualified": "Qualified (demo)",
    "quoted": "Quote recorded (demo)", "won": "Order recorded (demo)",
    "lost": "Lost (demo)", "opted_out": "Opted out (demo)", "closed": "Closed (demo)",
}


def status_label(status):
    return STATUS_LABELS.get(status, status.replace("_", " ").capitalize())


def readable_time(value):
    if not value:
        return "Not recorded"
    return datetime.fromisoformat(value).strftime("%b %d, %Y at %H:%M UTC")


def workflow_summary(store, opp):
    """Show the live next step separately from the agent's historical assessment.

    Returns whether a fresh analysis is the next available action. Reads only.
    """
    drafts = store.rows("SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1", (opp["id"],))
    draft = drafts[0] if drafts else None
    jobs = store.rows("""SELECT status FROM jobs WHERE opportunity_id=?
        AND kind IN ('analyze','prospect_research','prospect_qualify')
        AND json_extract(payload,'$.evidence_hash')=? ORDER BY created_at DESC,rowid DESC LIMIT 1""",
        (opp["id"], opp["evidence_hash"]))
    if opp["holds"]:
        st.warning("**On hold — verify the account first.** Resolve the identity or purchasing-channel questions in the evidence below before preparing outreach.")
    elif opp["status"] in STOPPED_STATUSES:
        st.info(f"**{status_label(opp['status'])}.** Automatic outreach has stopped. Review the recorded outcome below.")
    elif jobs and jobs[0]["status"] in ("failed", "blocked_config", "cancelled"):
        st.warning("**Analysis needs attention.** Open Activity to inspect the interrupted task and any error. Failed tasks require an explicit retry.")
    elif jobs and jobs[0]["status"] in ("queued", "running"):
        st.info("**Agent work in progress.** The agent will save its findings and prepare a draft if outreach is appropriate. Use Refresh results to check progress; no approval is needed yet.")
    elif draft and draft["evidence_hash"] != opp["evidence_hash"]:
        st.warning("**Purchase evidence has changed.** Prepare a new assessment before reviewing or approving an email.")
        return True
    elif draft and draft["status"] == "awaiting_approval":
        st.info("**Your review is needed.** Read the opportunity below, then review the email. Approve it for the simulation, edit it, or reject it.")
    elif draft and draft["status"] == "approved":
        st.info("**Approved — waiting for the simulation.** The background worker will record the approved email in Outreach history. No real email will be sent.")
        delivery = store.rows("SELECT status FROM jobs WHERE kind='deliver' AND json_extract(payload,'$.draft_id')=?", (draft["id"],))
        if delivery and delivery[0]["status"] in ("failed", "blocked_config", "cancelled"):
            st.warning("Simulation needs attention. Check Activity for the delivery task.")
    elif opp["status"] == "awaiting_response":
        st.success("**Outreach simulated — no action needed now.** Your approved email is saved in Outreach history. No real email was sent or customer response verified.")
    elif opp["status"] == "agent_held":
        st.warning("**The agent recommends investigating first.** Review its unresolved questions below. No email is ready for approval.")
    else:
        st.info("**Ready for the agent.** Review the evidence, then ask the agent to assess the opportunity and prepare an email if appropriate.")
        return True
    return False


def sales_controls(store, opp):
    st.divider()
    st.header("3. Approve outreach", anchor="approve-outreach")
    st.caption("You control this step. Review the proposed email, save any edits, then approve or reject the exact version.")
    drafts = store.rows("SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC", (opp["id"],))
    if drafts:
        draft = drafts[0]
        editable = (draft["status"] in ("awaiting_approval", "approved")
                    and draft["evidence_hash"] == opp["evidence_hash"]
                    and not opp["holds"] and opp["status"] not in STOPPED_STATUSES)
        st.markdown("**Email ready for review**" if editable else "**Saved email**")
        st.caption(f"Version {draft['version']} · {status_label(draft['status'])}")
        if editable:
            st.caption("Read and edit below. If you change anything, save your changes before approving. Approval creates a simulation only.")
            with st.form(f"edit-{draft['id']}"):
                subject = st.text_input("Subject", draft["subject"])
                body = st.text_area("Message", draft["body"], height=220)
                with st.expander("Simulation recipient"):
                    recipient = st.text_input("Simulated recipient", draft["recipient"])
                    st.caption("A placeholder for the local outbox. Nothing is delivered to this address.")
                approve = st.form_submit_button("Approve for simulated outbox", type="primary", disabled=draft["status"] != "awaiting_approval")
                save = st.form_submit_button("Save changes")
                reject = st.form_submit_button("Reject draft", disabled=draft["status"] != "awaiting_approval")
                try:
                    if save:
                        store.revise_draft(draft["id"], recipient, subject, body)
                        st.rerun()
                    elif approve:
                        if (recipient, subject, body) != (draft["recipient"], draft["subject"], draft["body"]):
                            st.error("Save your edits first. Approval must apply to the exact saved version.")
                        else:
                            store.decide(draft["id"], True)
                            st.rerun()
                    elif reject:
                        store.decide(draft["id"], False)
                        st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            st.caption("Approval binds the saved version. Only a simulated outbox entry can be created; no email provider is connected.")
        else:
            with st.expander("Read saved email"):
                st.text(draft["subject"])
                st.text(draft["body"])
    else:
        st.info("No email is ready yet. Complete the agent assessment in step 2; it will prepare a draft if outreach is appropriate.")
    st.divider()
    st.header("4. Track follow-up & results", anchor="track-results")
    st.caption("After approved outreach is simulated, the agent schedules one follow-up. Any new draft needs its own approval.")
    followups = store.rows("SELECT status,due_at FROM jobs WHERE opportunity_id=? AND kind='followup' ORDER BY created_at DESC", (opp["id"],))
    if followups:
        followup = followups[0]
        if followup["status"] == "queued":
            st.info(f"**Next follow-up: {readable_time(followup['due_at'])}.** The agent will check whether a follow-up is needed. Any new email requires your approval. Keep the worker running and the computer awake.")
        else:
            st.caption(f"Follow-up task: {followup['status'].replace('_', ' ')} · {readable_time(followup['due_at'])}. See Activity for details.")
    else:
        st.caption("No follow-up is scheduled for this account.")
    with st.expander("Record a response or result (demo)"):
        st.caption("Use this to demonstrate what happens after a customer responds. Recording a result stops automatic follow-ups for this account.")
        outcome_labels = {"reply":"Customer replied", "qualified":"Opportunity qualified", "quote":"Quote issued", "order":"Order received", "lost":"Opportunity lost", "opt_out":"Customer opted out", "closed":"Close opportunity"}
        kind = st.selectbox("Outcome", list(outcome_labels), format_func=outcome_labels.get, key=f"outcome-kind-{opp['id']}")
        with st.form(f"outcome-{opp['id']}"):
            note = st.text_area("Response / reason (recorded as manual demo input)")
            amount = st.number_input("Amount in USD (quote/order only)", min_value=0.0, value=0.0, step=1.0)
            reference = st.text_input("Unique quote/order reference")
            st.caption("Manual demo outcomes are not verified sales or proven incremental revenue. Responses and commercial milestones stop automatic follow-ups.")
            if st.form_submit_button("Record and stop follow-ups"):
                try:
                    store.record_outcome(opp["id"], kind, note, cents(amount), reference)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    history = store.rows("SELECT kind,note,reference,amount_cents,created_at FROM outcomes WHERE opportunity_id=? ORDER BY created_at DESC", (opp["id"],))
    if history:
        st.dataframe(history, width="stretch", hide_index=True)
