import streamlit as st
import pandas as pd
from database.db import get_connection, get_candidate_documents
from services.drive_service import load_settings
from services.pipeline import run_pipeline

settings = load_settings()
REQUIRED_DOCS = settings.get("required_docs", ["aadhaar", "pan", "10th_certificate"])

def get_failed_candidates():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT candidate_id, name, email, phone, status
        FROM candidates
        WHERE status = 'Failed'
        ORDER BY candidate_id
    """)
    data = cursor.fetchall()
    conn.close()
    return data


st.title("🔍 Review Queue")
st.caption("Failed candidates are listed here for manual review and retry.")

candidates = get_failed_candidates()

if not candidates:
    st.success("✅ No failed candidates. All done!")
    st.stop()

df = pd.DataFrame(
    candidates,
    columns=["Candidate ID", "Name", "Email", "Phone", "Status"]
)

st.dataframe(df, use_container_width=True)

st.divider()


st.subheader("🔄 Retry Verification")

candidate_options = {f"{c[0]} — {c[1]} ({c[4]})": c for c in candidates}
selected_label = st.selectbox("Select candidate to retry", list(candidate_options.keys()))
selected = candidate_options[selected_label]

candidate_id    = selected[0]
candidate_name  = selected[1]
candidate_email = selected[2]

st.write(f"**Email:** {candidate_email}")
st.write(f"**Current Status:** {selected[4]}")


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

if st.button("🔄 Retry Now", type="primary"):
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
    elif result["status"] == "Error":
        st.error(f"🛑 Something went wrong on our side, status left unchanged. Try again. ({result['error']})")
    else:
        st.error("❌ Still Failed. No required documents found in Gmail or Drive.")