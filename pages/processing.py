import os
import streamlit as st
from database.db import (
    get_all_candidates,
    get_candidate_documents,
    update_candidate_status,
    insert_document
)
from services.gmail_service import get_gmail_service, get_attachment_for_candidate
from services.document_classifier import classify_pdf_from_bytes, save_split_documents
from services.drive_service import upload_candidate_document

import json

def load_settings():
    if os.path.exists("data/settings.json"):
        with open("data/settings.json", "r") as f:
            return json.load(f)
    return {"required_docs": ["aadhaar", "pan", "10th_certificate"]}

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

    
    log("📧 Connecting to Gmail...")
    service = get_gmail_service()
    data = get_attachment_for_candidate(service, candidate_email)

    if data:
        log("✅ Attachment fetched from Gmail")
    else:
        log("⚠️ Not found in Gmail — checking Drive source folder...")
        source_folder = settings.get("drive_source_folder", "")
        if source_folder:
            from services.drive_service import get_pdf_from_drive_folder
            data = get_pdf_from_drive_folder(candidate_email, source_folder)
            if data:
                log("✅ Document found in Drive source folder")
            else:
                log("❌ Not found in Drive source folder either.")
                update_candidate_status(candidate_id, "Failed")
                st.error("Verification failed — no document found in Gmail or Drive.")
                st.stop()
        else:
            log("❌ No PDF found in Gmail and no Drive source folder configured in Settings.")
            update_candidate_status(candidate_id, "Failed")
            st.error("Verification failed — no attachment found.")
            st.stop()

  
    log("🔍 Classifying document pages...")
    page_results, temp_path = classify_pdf_from_bytes(data)
    log(f"Page classification: {page_results}")


    log("💾 Splitting and saving documents locally...")
    output_dir = f"uploads/{candidate_id}"
    saved = save_split_documents(temp_path, page_results, output_dir)
    log(f"Saved locally: {list(saved.keys())}")

    if not saved:
        log("❌ Could not classify any pages.")
        update_candidate_status(candidate_id, "Failed")
        st.error("Verification failed — documents could not be classified.")
        st.stop()


    log("☁️ Uploading to Google Drive...")
    uploaded_types = list(existing_types)

    for doc_type, file_path in saved.items():
        if doc_type == "unknown":
            log(f"⚠️ Skipping unrecognized page")
            continue
        if doc_type in existing_types:
            log(f"⏩ {doc_type} already exists — skipping duplicate")
            continue

        link = upload_candidate_document(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            file_path=file_path,
            doc_type=doc_type
        )
        insert_document(candidate_id, doc_type, file_path)
        uploaded_types.append(doc_type)
        log(f"✅ {doc_type} uploaded → {link}")


    found   = [d for d in REQUIRED_DOCS if d in uploaded_types]
    missing = [d for d in REQUIRED_DOCS if d not in uploaded_types]

    if len(found) == len(REQUIRED_DOCS):
        status = "Completed"
    elif len(found) > 0:
        status = "Partial"
    else:
        status = "Failed"

    update_candidate_status(candidate_id, status)
    log(f"📊 Status updated → {status}")
    log(f"Found: {found}")
    log(f"Missing: {missing}")

    st.divider()

    if status == "Completed":
        st.success(f"✅ {candidate_name} — Verification Completed!")
    elif status == "Partial":
        st.warning(f"⚠️ Partial — still missing: {missing}")
    else:
        st.error(f"❌ Failed — no required documents found")