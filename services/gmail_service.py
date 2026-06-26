import base64
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive.file'
]

def get_gmail_service():

    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES
        )

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