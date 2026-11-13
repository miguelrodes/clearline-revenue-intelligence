"""Navigation and shared controls; agent execution belongs to the worker."""
import os
import streamlit as st
from clearline.config import Settings
from clearline.store import Store

st.set_page_config(page_title="Clearline | Revenue Intelligence", layout="wide")
st.set_option("client.toolbarMode", "minimal")
settings = Settings.load()
store = Store(settings.db_path)

page = st.navigation({
    "Agents": [
        st.Page("views/recovery.py", title="Customer Recovery Agent", default=True),
        st.Page("views/prospecting.py", title="Prospecting Agent"),
    ],
    "Monitoring": [
        st.Page("views/activity.py", title="Activity"),
        st.Page("views/outreach.py", title="Outreach history"),
    ],
}, position="top")

with st.sidebar:
    st.subheader("Background execution")
    if st.button("Refresh results", width="stretch"):
        st.rerun()
    st.caption("Refresh after agent work finishes to see its saved results.")
    with st.expander("Execution settings"):
        st.caption(f"Business cutoff: {settings.as_of} · Model: {settings.model} · Reasoning: {settings.reasoning}")
        paused = store.paused()
        if st.button("Resume background work" if paused else "Pause new background work"):
            store.set_paused(not paused)
            st.rerun()
        st.caption("Start the worker separately: clearline worker. Open Monitoring → Activity to check whether it is running.")
if store.paused():
    st.warning("Background work is paused. Resume it in Execution settings in the sidebar.")
if not os.getenv("OPENAI_API_KEY", "").strip():
    st.info("AI access needs setup: add OPENAI_API_KEY to the local .env file. Purchase scans still work.")

page.run()
