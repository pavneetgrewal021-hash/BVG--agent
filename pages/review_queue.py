import os
import streamlit as st
import pandas as pd
from database.db import get_connection, update_candidate_status
from services.gmail_service import get_gmail_service, get_attachment_for_candidate
from services.document_classifier import classify_pdf_from_bytes, save_split_documents
from services.drive_service import upload_candidate_document, get_drive_service
from database.db import insert_document, get_candidate_documents

import json

def load_settings():
    if os.path.exists("data/settings.json"):
        with open("data/settings.json", "r") as f:
            return json.load(f)
    return {"required_docs": ["aadhaar", "pan", "10th_certificate"]}

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


def run_pipeline_for_candidate(candidate_id, candidate_name, candidate_email):
    """
    Re-runs the full pipeline for a single candidate.
    Returns a result dict with status and details.
    """
    logs = []

    logs.append("📧 Fetching attachment from Gmail...")
    service = get_gmail_service()
    data = get_attachment_for_candidate(service, candidate_email)

    if not data:
        logs.append("❌ No attachment found in Gmail for this candidate")
        update_candidate_status(candidate_id, "Failed")
        return {"status": "Failed", "logs": logs}

    logs.append("✅ Attachment fetched")

  
    logs.append("🔍 Classifying pages...")
    page_results, temp_path = classify_pdf_from_bytes(data)
    logs.append(f"Page results: {page_results}")

  
    logs.append("💾 Saving split documents...")
    output_dir = f"uploads/{candidate_id}"
    saved = save_split_documents(temp_path, page_results, output_dir)
    logs.append(f"Saved: {list(saved.keys())}")

    if not saved:
        logs.append("❌ No documents could be classified")
        update_candidate_status(candidate_id, "Failed")
        return {"status": "Failed", "logs": logs}


    existing_docs = get_candidate_documents(candidate_id)
    existing_types = [row[2] for row in existing_docs]
    logs.append(f"Already in DB: {existing_types}")

   
    logs.append("☁️ Uploading to Drive...")
    uploaded_types = list(existing_types)

    for doc_type, file_path in saved.items():
        if doc_type == "unknown":
            logs.append(f"⚠️ Skipping unknown doc")
            continue
        if doc_type in existing_types:
            logs.append(f"⏩ {doc_type} already exists — skipping")
            continue

        link = upload_candidate_document(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            file_path=file_path,
            doc_type=doc_type
        )
        insert_document(candidate_id, doc_type, file_path)
        uploaded_types.append(doc_type)
        logs.append(f"✅ {doc_type} uploaded")

  
    found = [d for d in REQUIRED_DOCS if d in uploaded_types]
    missing = [d for d in REQUIRED_DOCS if d not in uploaded_types]

    if len(found) == len(REQUIRED_DOCS):
        status = "Completed"
    elif len(found) > 0:
        status = "Partial"
    else:
        status = "Failed"

    update_candidate_status(candidate_id, status)
    logs.append(f"📊 Status → {status}")
    logs.append(f"Found: {found}")
    logs.append(f"Missing: {missing}")

    return {
        "status": status,
        "logs": logs,
        "found": found,
        "missing": missing
    }



st.title("🔍 Review Queue")
st.caption("Failed candidates are listed here for manual review and retry.")

candidates = get_failed_candidates()

if not candidates:
    st.success("✅ No failed or pending candidates. All done!")
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
    with st.spinner("Running verification pipeline..."):
        result = run_pipeline_for_candidate(
            candidate_id,
            candidate_name,
            candidate_email
        )


    st.subheader("Pipeline Logs")
    for log in result["logs"]:
        st.write(log)


    if result["status"] == "Completed":
        st.success(f"✅ Candidate {candidate_id} is now Completed!")
    elif result["status"] == "Partial":
        st.warning(f"⚠️ Still Partial. Missing: {result.get('missing', [])}")
    else:
        st.error(f"❌ Still Failed. No required documents found in Gmail.")