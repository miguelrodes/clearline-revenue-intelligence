"""Shared human review and simulated action controls for both workflows."""
import streamlit as st
from .data import cents


def sales_controls(store, opp):
    drafts = store.rows("SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC", (opp["id"],))
    if drafts:
        draft = drafts[0]
        st.subheader(f"Draft version {draft['version']} · {draft['status']}")
        if draft["status"] in ("awaiting_approval", "approved"):
            with st.form(f"edit-{draft['id']}"):
                recipient = st.text_input("Simulated recipient", draft["recipient"])
                subject = st.text_input("Subject", draft["subject"])
                body = st.text_area("Message", draft["body"], height=220)
                save = st.form_submit_button("Save a revised draft")
                approve = st.form_submit_button("Approve for simulated outbox", disabled=draft["status"] != "awaiting_approval")
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
            st.text(draft["subject"])
            st.text(draft["body"])
    followups = store.rows("SELECT status,due_at FROM jobs WHERE opportunity_id=? AND kind='followup' ORDER BY created_at DESC", (opp["id"],))
    if followups:
        st.write(f"Follow-up: {followups[0]['status']} · {followups[0]['due_at']} (UTC)")
    with st.expander("Record a demo outcome"):
        kind = st.selectbox("Outcome", ["reply", "qualified", "quote", "order", "lost", "opt_out", "closed"], key=f"outcome-kind-{opp['id']}")
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
