from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from datetime import datetime
import os
import re
import mimetypes
import json

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive.file'
]

DOC_TYPE_FOLDER = {
    "aadhaar":              "Identity",
    "pan":                  "Identity",
    "passport":             "Identity",
    "driving_license":      "Identity",
    "voter_id":             "Identity",
    "10th_certificate":     "Education",
    "12th_certificate":     "Education",
    "degree_certificate":   "Education",
    "provisional_certificate": "Education",
    "marksheet":            "Education",
    "offer_letter":         "Employment",
    "appointment_letter":   "Employment",
    "experience_letter":    "Employment",
    "relieving_letter":     "Employment",
    "payslip":              "Employment",
    "form_16":              "Financial",
    "bank_statement":       "Financial",
    "itr":                  "Financial",
    "cancelled_cheque":     "Financial",
    "police_verification":  "Compliance",
    "drug_test":            "Compliance",
    "nda":                  "Compliance",
    "bgv_consent":          "Compliance",
    "visa":                 "International",
    "work_permit":          "International",
    "electricity_bill":  "Address",
    "water_bill":        "Address",
    "gas_bill":          "Address",
    "telephone_bill":    "Address",
    "rental_agreement":  "Address",
    "police_clearance":  "Criminal",
    "court_record":      "Criminal",
    "unknown":              "Others"
}

SETTINGS_FILE = "data/settings.json"

DEFAULT_SETTINGS = {
    "required_docs": ["aadhaar", "pan", "10th_certificate"],
    "drive_root_folder": "BGV_Candidates",
    "folder_name_pattern": "{candidate_id}-{name}-{date}",
    "file_name_pattern": "{name}_{date}_{doc_type}",
    "classifier": "keyword",
    "llm_provider": "ollama",
    "llm_model": "qwen3:4b",
    "extract_model": "qwen3:4b"
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_SETTINGS.copy()


def get_drive_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build("drive", "v3", credentials=creds)
    return service


def create_folder(service, folder_name, parent_id=None):
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=metadata,
        fields="id"
    ).execute()

    return folder["id"]


def escape_query_value(value):
    """Escapes a value for a Drive query string, so names like O'Brien don't break it."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def file_name_matches(email_prefix, file_name):
    """True if email_prefix appears in file_name as a whole token.
    'raj' matches 'raj_docs.pdf' and 'docs-raj.pdf' but not 'rajesh_docs.pdf'."""
    pattern = r"(^|[^a-z0-9])" + re.escape(email_prefix.lower()) + r"($|[^a-z0-9])"
    return re.search(pattern, file_name.lower()) is not None


def get_or_create_folder(service, folder_name, parent_id=None):
    query = f"name='{escape_query_value(folder_name)}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]
    else:
        return create_folder(service, folder_name, parent_id)


def upload_candidate_document(candidate_id, candidate_name, file_path, doc_type):
    settings = load_settings()

    service = get_drive_service()

    # Root folder from settings
    root_folder = settings.get("drive_root_folder", "BGV_Candidates")
    root_id = get_or_create_folder(service, root_folder)

    # Candidate folder — just candidate_id as per requirement
    candidate_folder_name = f"{candidate_id}. {candidate_name}"
    candidate_folder_id = get_or_create_folder(service, candidate_folder_name, root_id)

    # Subfolder by doc type
    sub_folder_name = DOC_TYPE_FOLDER.get(doc_type, "Others")
    sub_folder_id = get_or_create_folder(service, sub_folder_name, candidate_folder_id)

    # File name from settings pattern
    _, ext = os.path.splitext(file_path)
    if not ext:
        ext = ".pdf"

    date_str_file = datetime.now().strftime("%Y%m%d")
    file_pattern = settings.get("file_name_pattern", "{name}_{date}_{doc_type}")
    file_name = (
        file_pattern
        .replace("{name}", candidate_name.replace(" ", "_"))
        .replace("{date}", date_str_file)
        .replace("{doc_type}", doc_type)
        .replace("{candidate_id}", str(candidate_id))
    ) + ext

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

    file_metadata = {
        "name": file_name,
        "parents": [sub_folder_id]
    }

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()

    return uploaded.get("webViewLink")

def get_pdf_from_drive_folder(candidate_email, source_folder_name):
    
    import io
    from googleapiclient.http import MediaIoBaseDownload

    try:
        service = get_drive_service()

        # Find source folder
        query = f"name='{escape_query_value(source_folder_name)}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])

        if not folders:
            return None

        source_folder_id = folders[0]["id"]

        # Search for PDF in source folder
        email_prefix = candidate_email.split("@")[0]
        query = f"'{source_folder_id}' in parents and mimeType='application/pdf' and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        if not files:
            return None

        # Never guess: a wrong match would file another candidate's documents under this one
        matches = [f for f in files if file_name_matches(email_prefix, f["name"])]

        if len(matches) != 1:
            print(f"Drive source: {len(matches)} files match '{email_prefix}', expected exactly 1")
            return None

        matched_file = matches[0]

        request = service.files().get_media(fileId=matched_file["id"])
        file_bytes = io.BytesIO()
        downloader = MediaIoBaseDownload(file_bytes, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        return file_bytes.getvalue()

    except Exception as e:
        print(f"Drive source fetch error: {e}")
        return None