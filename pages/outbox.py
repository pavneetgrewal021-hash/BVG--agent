import streamlit as st
import pandas as pd
from database.db import get_followups
from services.drive_service import load_settings
from services.followup import approve_followup, check_followup_row, prepare_followups, reject_followup
from services.gmail_service import get_gmail_service

settings = load_settings()

st.title("📮 Outbox")
st.caption("Follow-up emails written for candidates who still owe documents or whose documents disagree. "
           "Nothing is sent from here: approving creates a Gmail draft, which a person sends from Gmail.")

if "outbox_message" in st.session_state:
    st.success(st.session_state.pop("outbox_message"))

if st.button("📝 Prepare follow-ups", type="primary"):
    logs = []
    with st.spinner("Checking every candidate and writing drafts..."):
        created = prepare_followups(settings, log=logs.append)
    for line in logs:
        st.write(line)
    if not created:
        st.info("No candidate needs a new follow-up right now.")

st.divider()

pending = get_followups("pending")
st.subheader(f"Waiting for approval ({len(pending)})")

if not pending:
    st.info("Nothing waiting. Use 'Prepare follow-ups' to check all candidates.")

for row in pending:
    followup_id, candidate_id, action, reason, to_email, subject, body, source = row[:8]
    label = "Escalation to HR" if action == "escalate_to_hr" else action.replace("_", " ").capitalize()
    with st.expander(f"{candidate_id} — {label} — to {to_email or '(set the HR email in Settings)'}", expanded=True):
        st.caption(f"Why: {reason}. Written by: {source}.")
        new_subject = st.text_input("Subject", value=subject, key=f"subject_{followup_id}")
        new_body = st.text_area("Body", value=body, height=260, key=f"body_{followup_id}")

        problems = check_followup_row((followup_id, candidate_id, action, reason, to_email, new_subject, new_body),
                                      settings)
        for p in problems:
            st.warning(f"Check: the email {p}.")

        col1, col2 = st.columns(2)
        if col1.button("✅ Approve → create Gmail draft", key=f"approve_{followup_id}", disabled=not to_email):
            try:
                approve_followup(followup_id, new_subject, new_body, get_gmail_service())
                st.session_state["outbox_message"] = f"Gmail draft created for {candidate_id}. Send it from Gmail."
                st.rerun()
            except Exception as e:
                st.error(f"Could not create the Gmail draft: {e}")
        if col2.button("🗑️ Reject", key=f"reject_{followup_id}"):
            reject_followup(followup_id)
            st.session_state["outbox_message"] = f"Draft for {candidate_id} rejected."
            st.rerun()

st.divider()

st.subheader("History")
done = [r for r in get_followups() if r[8] != "pending"]
if done:
    st.dataframe(
        pd.DataFrame([(r[1], r[2], r[8], r[5], r[7], r[10]) for r in done],
                     columns=["Candidate", "Action", "Decision", "Subject", "Written by", "Created"]),
        width="stretch",
        hide_index=True
    )
else:
    st.caption("No decisions yet.")
