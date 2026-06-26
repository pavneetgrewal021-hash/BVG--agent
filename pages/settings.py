import streamlit as st
import json
import os
from services.gmail_service import get_gmail_service
from services.drive_service import get_drive_service, get_or_create_folder

SETTINGS_FILE = "data/settings.json"

DEFAULT_SETTINGS = {
    "required_docs": ["aadhaar", "pan", "10th_certificate"],
    "drive_root_folder": "BGV_Candidates",
    "folder_name_pattern": "{candidate_id}-{name}-{date}",
    "file_name_pattern": "{name}_{doc_type}"
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    os.makedirs("data", exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)



settings = load_settings()


st.subheader("📋 Required Documents")
st.caption("These are the documents that must be present for a candidate to be marked Completed.")

ALL_DOCS = [
    "aadhaar",
    "pan",
    "passport",
    "10th_certificate",
    "12th_certificate",
    "degree_certificate",
    "offer_letter",
    "experience_letter",
    "relieving_letter",
    "payslip",
    "form_16",
    "police_verification",
    "drug_test"
]

selected_docs = st.multiselect(
    "Select required documents",
    options=ALL_DOCS,
    default=settings.get("required_docs", DEFAULT_SETTINGS["required_docs"])
)

st.caption("Or upload an Excel file with a column named 'DocumentType' to set required docs.")
excel_file = st.file_uploader("Upload Required Docs Excel", type=["xlsx"], key="docs_excel")

if excel_file:
    import pandas as pd
    docs_df = pd.read_excel(excel_file)
    if "DocumentType" in docs_df.columns:
        uploaded_docs = docs_df["DocumentType"].dropna().str.strip().str.lower().tolist()
        valid_docs = [d for d in uploaded_docs if d in ALL_DOCS]
        invalid_docs = [d for d in uploaded_docs if d not in ALL_DOCS]
        if valid_docs:
            selected_docs = valid_docs
            st.success(f"✅ Loaded {len(valid_docs)} docs from Excel: {valid_docs}")
        if invalid_docs:
            st.warning(f"⚠️ These were not recognized and skipped: {invalid_docs}")
    else:
        st.error("❌ Excel must have a column named 'DocumentType'")


st.subheader("📁 Google Drive Folder Settings")

drive_root = st.text_input(
    "Root folder name on Drive",
    value=settings.get("drive_root_folder", "BGV_Candidates")
)

drive_source = st.text_input(
    "Source folder name on Drive (where candidates upload docs)",
    value=settings.get("drive_source_folder", ""),
    help="Leave empty if using Gmail only"
)

folder_pattern = st.text_input(
    "Candidate folder name pattern",
    value=settings.get("folder_name_pattern", "{candidate_id}-{name}-{date}"),
    help="Available variables: {candidate_id}, {name}, {date}"
)

file_pattern = st.text_input(
    "File name pattern",
    value=settings.get("file_name_pattern", "{name}_{doc_type}"),
    help="Available variables: {name}, {doc_type}, {candidate_id}"
)

st.caption(f"Example folder: **{folder_pattern.replace('{candidate_id}', 'C101').replace('{name}', 'Satwik').replace('{date}', '2026-06-24')}**")


if st.button("💾 Save Settings"):
    settings["required_docs"]        = selected_docs
    settings["drive_root_folder"]    = drive_root
    settings["drive_source_folder"]  = drive_source
    settings["folder_name_pattern"]  = folder_pattern
    settings["file_name_pattern"]    = file_pattern
    save_settings(settings)
    st.success("Settings saved successfully!")

st.divider()


st.subheader("📧 Gmail Connection")

col1, col2 = st.columns([3, 1])

with col1:
    if os.path.exists("token.json"):
        st.success("✅ Gmail is connected")
    else:
        st.error("❌ Gmail not connected")

with col2:
    if st.button("Reconnect Gmail"):
        try:
            if os.path.exists("token.json"):
                os.remove("token.json")
            get_gmail_service()
            st.success("Gmail reconnected!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")


st.subheader("☁️ Google Drive Connection")

col3, col4 = st.columns([3, 1])

with col3:
    if os.path.exists("token.json"):
        st.success("✅ Drive is connected")
    else:
        st.error("❌ Drive not connected")

with col4:
    if st.button("Reconnect Drive"):
        try:
            if os.path.exists("token.json"):
                os.remove("token.json")
            get_drive_service()
            st.success("Drive reconnected!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")


st.divider()
st.subheader("🧪 Test Drive Connection")
st.caption("Creates the root BGV folder on your Drive to confirm everything is working.")

if st.button("Test Drive Upload"):
    try:
        service = get_drive_service()
        folder_id = get_or_create_folder(service, drive_root)
        st.success(f"✅ Connected! Root folder '{drive_root}' is ready on Drive. Folder ID: `{folder_id}`")
    except Exception as e:
        st.error(f"❌ Drive test failed: {e}")