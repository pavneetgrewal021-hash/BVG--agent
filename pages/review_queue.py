import streamlit as st
import pandas as pd
from database.db import get_connection, get_candidate_documents, get_extracted_fields, get_open_flags
from services.drive_service import load_settings
from services.pipeline import approve_after_review, run_pipeline

settings = load_settings()
REQUIRED_DOCS = settings.get("required_docs", ["aadhaar", "pan", "10th_certificate"])

def get_review_candidates():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT candidate_id, name, email, phone, status
        FROM candidates
        WHERE status IN ('Failed', 'Needs Review')
        ORDER BY status DESC, candidate_id
    """)
    data = cursor.fetchall()
    conn.close()
    return data


st.title("🔍 Review Queue")
st.caption("Candidates whose documents disagree (Needs Review) or who sent nothing usable (Failed).")

# Set by the Approve button; kept in session state so it survives the rerun that refreshes the list
if "review_message" in st.session_state:
    st.success(st.session_state.pop("review_message"))

candidates = get_review_candidates()

if not candidates:
    st.success("✅ Nothing to review. All done!")
    st.stop()

df = pd.DataFrame(
    candidates,
    columns=["Candidate ID", "Name", "Email", "Phone", "Status"]
)

st.dataframe(df, width="stretch")

st.divider()


st.subheader("🧐 Review a Candidate")

candidate_options = {f"{c[0]} — {c[1]} ({c[4]})": c for c in candidates}
selected_label = st.selectbox("Select candidate", list(candidate_options.keys()))
selected = candidate_options[selected_label]

candidate_id    = selected[0]
candidate_name  = selected[1]
candidate_email = selected[2]
current_status  = selected[4]

st.write(f"**Email:** {candidate_email}")
st.write(f"**Current Status:** {current_status}")

flags = get_open_flags(candidate_id)
if flags:
    st.write("**Problems found across the documents:**")
    for flag_type, document_type, detail in flags:
        st.warning(f"🚩 {flag_type.replace('_', ' ').capitalize()} on **{document_type}**: {detail}")

    extracted = get_extracted_fields(candidate_id)
    if extracted:
        with st.expander("Details read from each document"):
            st.dataframe(
                pd.DataFrame(extracted, columns=["Document", "Field", "Value", "Check", "Source", "Note"]),
                width="stretch",
                hide_index=True
            )


existing_docs = get_candidate_documents(candidate_id)
if existing_docs:
    st.write("**Documents already received:**")
    for doc in existing_docs:
        st.write(f"  ✅ {doc[2]}")

missing = [d for d in REQUIRED_DOCS if d not in [doc[2] for doc in existing_docs]]
if missing:
    st.write("**Still missing:**")
    for doc in missing:
        st.write(f"  ❌ {doc}")

st.divider()

col1, col2 = st.columns(2)

if current_status == "Needs Review" and col2.button("✅ Approve: I checked the documents"):
    new_status = approve_after_review(candidate_id, REQUIRED_DOCS)
    st.session_state["review_message"] = f"Flags closed. {candidate_id} is now {new_status}."
    st.rerun()

if col1.button("🔄 Retry Now", type="primary"):
    logs = []
    with st.spinner("Running verification pipeline..."):
        result = run_pipeline(
            candidate_id,
            candidate_name,
            candidate_email,
            settings,
            log=logs.append
        )


    st.subheader("Pipeline Logs")
    for log in logs:
        st.write(log)


    if result["status"] == "Completed":
        st.success(f"✅ Candidate {candidate_id} is now Completed!")
    elif result["status"] == "Partial":
        st.warning(f"⚠️ Now Partial. Missing: {result['missing']}")
    elif result["status"] == "Needs Review":
        st.warning(f"🚩 Documents disagree ({len(result['flags'])} problem(s)). A person must review them.")
    elif result["status"] == "Error":
        st.error(f"🛑 Something went wrong on our side, status left unchanged. Try again. ({result['error']})")
    else:
        st.error("❌ Still Failed. No required documents found in Gmail or Drive.")
