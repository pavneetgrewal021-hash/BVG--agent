import base64
import os
from email.message import EmailMessage
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# gmail.compose lets the app create drafts for follow-up emails. It cannot read other
# mail beyond gmail.readonly, and the app never calls send: a person sends from Gmail.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/drive.file'
]

def load_credentials():
    """token.json if it grants every scope in SCOPES; None if the user must sign in again."""
    if not os.path.exists("token.json"):
        return None
    # Load with the scopes stored in the file (not SCOPES), so has_scopes sees what was really granted
    creds = Credentials.from_authorized_user_file("token.json")
    if not creds.has_scopes(SCOPES):
        return None  # e.g. a token from before gmail.compose was added: ask for consent again
    if not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            return None  # refresh refused (e.g. access revoked): sign in again instead of crashing
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds

def get_gmail_service():

    creds = load_credentials()

    if not creds:

        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )

        creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build(
        "gmail",
        "v1",
        credentials=creds
    )

    return service
def create_draft(service, to, subject, body):
    """Creates a Gmail draft (not sent). Returns the draft id."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()

    return draft["id"]

def download_pdf_attachments(service):

    results = service.users().messages().list(
        userId="me",
        maxResults=20
    ).execute()

    messages = results.get("messages", [])

    downloaded_files = []

    for msg in messages:

        message = service.users().messages().get(
            userId="me",
            id=msg["id"]
        ).execute()

        payload = message.get("payload", {})
        parts = payload.get("parts", [])

        for part in parts:

            filename = part.get("filename")

            if filename and filename.lower().endswith(".pdf"):

                attachment_id = part["body"].get("attachmentId")

                if attachment_id:

                    attachment = service.users().messages().attachments().get(
                        userId="me",
                        messageId=msg["id"],
                        id=attachment_id
                    ).execute()

                    data = attachment["data"]

                    file_data = base64.urlsafe_b64decode(data)

                    save_path = os.path.join(
                        "downloads",
                        filename
                    )

                    with open(save_path, "wb") as f:
                        f.write(file_data)

                    downloaded_files.append(filename)

    return downloaded_files
def get_recent_emails(service):

    results = service.users().messages().list(
        userId="me",
        maxResults=100
    ).execute()

    messages = results.get("messages", [])

    email_data = []

    for msg in messages:

        message = service.users().messages().get(
            userId="me",
            id=msg["id"]
        ).execute()

        headers = message["payload"].get(
            "headers",
            []
        )

        sender = ""
        subject = ""

        for header in headers:

            if header["name"] == "From":
                sender = header["value"]

            if header["name"] == "Subject":
                subject = header["value"]

        parts = message["payload"].get(
            "parts",
            []
        )

        has_pdf = False

        for part in parts:

            filename = part.get("filename", "")

            if filename.lower().endswith(".pdf"):
                has_pdf = True

        if has_pdf:

            email_data.append({
                "sender": sender,
                "subject": subject
            })

    return email_data

def get_attachment_for_candidate(service, candidate_email):

    query = f"from:{candidate_email} has:attachment filename:pdf"

    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=1
    ).execute()

    messages = results.get("messages", [])

    if not messages:
        return None

    message = service.users().messages().get(
        userId="me",
        id=messages[0]["id"]
    ).execute()

    parts = message.get("payload", {}).get("parts", [])

    for part in parts:

        filename = part.get("filename", "")

        if filename.lower().endswith(".pdf"):

            attachment_id = part["body"].get("attachmentId")

            if attachment_id:

                attachment = service.users().messages().attachments().get(
                    userId="me",
                    messageId=messages[0]["id"],
                    id=attachment_id
                ).execute()

                file_data = base64.urlsafe_b64decode(attachment["data"])

                return file_data

    return None