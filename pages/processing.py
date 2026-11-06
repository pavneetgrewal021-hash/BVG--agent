import streamlit as st
from database.db import get_all_candidates, get_candidate_documents
from services.drive_service import load_settings
from services.pipeline import run_pipeline

settings = load_settings()
REQUIRED_DOCS = settings.get("required_docs", ["aadhaar", "pan", "10th_certificate"])


st.title("⚙️ Candidate Processing")
st.caption("Select a candidate and run the full verification pipeline — fetches from Gmail, classifies, uploads to Drive.")

candidates = get_all_candidates()

if not candidates:
    st.warning("No candidates found. Please upload candidates first.")
    st.stop()


candidate_options = {f"{c[0]} — {c[1]} ({c[4]})": c for c in candidates}
selected_label = st.selectbox("Select Candidate", list(candidate_options.keys()))
selected = candidate_options[selected_label]

candidate_id    = selected[0]
candidate_name  = selected[1]
candidate_email = selected[2]
current_status  = selected[4]

col1, col2, col3 = st.columns(3)
col1.metric("Candidate ID", candidate_id)
col2.metric("Email", candidate_email)
col3.metric("Current Status", current_status)


st.subheader("📄 Documents Received So Far")
existing_docs  = get_candidate_documents(candidate_id)
existing_types = [row[2] for row in existing_docs]

if existing_docs:
    for doc in existing_docs:
        st.write(f"✅ {doc[2]} — `{doc[3]}`")
else:
    st.info("No documents received yet.")

missing = [d for d in REQUIRED_DOCS if d not in existing_types]
if missing:
    st.write("**Missing:**")
    for m in missing:
        st.write(f"❌ {m}")

st.divider()


st.subheader("🚀 Run Verification Pipeline")

if st.button("▶️ Start Verification", type="primary"):

    log_box = st.empty()
    logs = []

    def log(msg):
        logs.append(msg)
        log_box.markdown("\n\n".join(logs))

    result = run_pipeline(candidate_id, candidate_name, candidate_email, settings, log=log)
    status = result["status"]

    st.divider()

    if status == "Completed":
        st.success(f"✅ {candidate_name} — Verification Completed!")
    elif status == "Partial":
        st.warning(f"⚠️ Partial — still missing: {result['missing']}")
    elif status == "Error":
        st.error(f"🛑 Something went wrong on our side, status left unchanged. Try again. ({result['error']})")
    else:
        st.error("❌ Failed — no required documents found")