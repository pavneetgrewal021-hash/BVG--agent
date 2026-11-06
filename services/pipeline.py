import os

from database.db import get_candidate_documents, insert_document, update_candidate_status
from services.gmail_service import get_gmail_service, get_attachment_for_candidate
from services.drive_service import get_pdf_from_drive_folder, upload_candidate_document
from services.document_classifier import classify_pdf_from_bytes, save_split_documents


def compute_status(required_docs, uploaded_types):
    """Returns (status, found, missing) for the required docs."""
    found = [d for d in required_docs if d in uploaded_types]
    missing = [d for d in required_docs if d not in uploaded_types]

    if len(found) == len(required_docs):
        status = "Completed"
    elif len(found) > 0:
        status = "Partial"
    else:
        status = "Failed"

    return status, found, missing


def fetch_candidate_pdf(candidate_email, source_folder, log):
    """Gmail first, then the Drive source folder. Returns PDF bytes or None."""
    log("📧 Connecting to Gmail...")
    service = get_gmail_service()
    data = get_attachment_for_candidate(service, candidate_email)

    if data:
        log("✅ Attachment fetched from Gmail")
        return data

    if not source_folder:
        log("❌ No PDF found in Gmail and no Drive source folder configured in Settings.")
        return None

    log("⚠️ Not found in Gmail — checking Drive source folder...")
    data = get_pdf_from_drive_folder(candidate_email, source_folder)

    if data:
        log("✅ Document found in Drive source folder")
    else:
        log("❌ Not found in Drive source folder either.")
    return data


def run_pipeline(candidate_id, candidate_name, candidate_email, settings, log=print):
    """
    Fetch -> classify -> split -> upload -> status, for one candidate.

    Returns {"status", "found", "missing", "error"}. Status is one of
    Completed / Partial / Failed, or "Error" when the system itself broke
    (API down, expired login...). On "Error" the candidate's status is left
    unchanged, because the candidate did nothing wrong and a retry may work.
    """
    required_docs = settings.get("required_docs", ["aadhaar", "pan", "10th_certificate"])
    temp_path = None

    try:
        data = fetch_candidate_pdf(candidate_email, settings.get("drive_source_folder", ""), log)

        if not data:
            update_candidate_status(candidate_id, "Failed")
            status, found, missing = compute_status(required_docs, [])
            return {"status": "Failed", "found": found, "missing": missing, "error": None}

        log("🔍 Classifying document pages...")
        page_results, temp_path = classify_pdf_from_bytes(data)
        log(f"Page classification: {page_results}")

        if "unknown" in page_results:
            log(f"⚠️ {len(page_results['unknown'])} page(s) not recognised — not uploaded")

        log("💾 Splitting and saving documents locally...")
        saved = save_split_documents(temp_path, page_results, f"uploads/{candidate_id}")
        log(f"Saved locally: {list(saved.keys())}")

        existing_types = [row[2] for row in get_candidate_documents(candidate_id)]
        uploaded_types = list(existing_types)

        if saved:
            log("☁️ Uploading to Google Drive...")
        else:
            log("❌ Could not classify any pages.")

        for doc_type, file_path in saved.items():
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

        status, found, missing = compute_status(required_docs, uploaded_types)
        update_candidate_status(candidate_id, status)
        log(f"📊 Status updated → {status}")
        log(f"Found: {found}")
        log(f"Missing: {missing}")

        return {"status": status, "found": found, "missing": missing, "error": None}

    except Exception as e:
        log(f"🛑 Pipeline error: {e}")
        return {"status": "Error", "found": [], "missing": [], "error": str(e)}

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
