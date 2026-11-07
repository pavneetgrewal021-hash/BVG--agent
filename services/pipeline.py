import os

from database.db import (get_candidate_documents, get_identity_fields, insert_document, insert_extracted_fields,
                         mark_flags_reviewed, replace_flags, update_candidate_status)
from services.consistency import check_candidate
from services.gmail_service import get_gmail_service, get_attachment_for_candidate
from services.drive_service import get_pdf_from_drive_folder, upload_candidate_document
from services.document_classifier import write_temp_pdf, save_documents
from services.ai_classifier import classify_pdf
from services.extractor import extract_document
from services.validators import mask_aadhaar


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


def approve_after_review(candidate_id, required_docs):
    """A person has checked the flagged documents: close the flags and set the normal status."""
    mark_flags_reviewed(candidate_id)
    present = [row[2] for row in get_candidate_documents(candidate_id)]
    status, _, _ = compute_status(required_docs, present)
    update_candidate_status(candidate_id, status)
    return status


def log_page_results(page_results, log):
    for r in page_results:
        line = f"Page {r['page'] + 1}: {r['doc_type']}"
        if r["continues_previous_page"]:
            line += " (continued)"
        if r["method"] == "llm":
            line += f" — evidence “{r['evidence']}”"
        if r["doc_type"] == "unknown":
            line += " — not a verification document, not uploaded"
        if r["keyword_type"] != r["doc_type"]:
            line += f" ⚠️ keyword rules say {r['keyword_type']}: please review"
        log(line)


def extract_and_store(document_id, candidate_id, document, settings, log):
    """Reads name / DOB / number / issue date from one document, logs them and stores them."""
    extract_settings = {**settings, "llm_model": settings.get("extract_model") or settings.get("llm_model")}
    result = extract_document(document["doc_type"], document["text"], extract_settings)
    fields = result["fields"]

    number = fields["doc_number"]
    if document["doc_type"] == "aadhaar" and number["value"]:
        number["value"] = mask_aadhaar(number["value"])  # checked in full above, stored masked

    insert_extracted_fields(document_id, candidate_id, document["doc_type"], fields)

    if result["error"]:
        log(f"⚠️ LLM unavailable for field extraction ({result['error']}) — used regex rules")
    shown = []
    for name, f in fields.items():
        if f["status"] == "ok":
            shown.append(f"{name} ✓ {f['value']}")
        elif f["status"] == "invalid":
            shown.append(f"{name} ⚠️ {f['value']} ({f['note']})")
        elif f["status"] == "dropped":
            shown.append(f"{name} ✗ dropped: {f['note']}")
    log(f"🔎 {document['doc_type']}: " + (" | ".join(shown) or "no fields found"))
    return fields


def document_provenance(document, page_results):
    """(classified_by, confidence) for the database: who labelled the document and how sure it was."""
    if not page_results:
        return "keyword", None
    pages = [page_results[p] for p in document["pages"]]
    if all(p["method"] == "llm" for p in pages):
        return "llm", min(p["confidence"] for p in pages)
    return "keyword_fallback", None


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
            return {"status": "Failed", "found": found, "missing": missing, "flags": [], "error": None}

        temp_path = write_temp_pdf(data)
        method = "the local LLM" if settings.get("classifier") == "llm" else "keyword rules"
        log(f"🔍 Classifying document pages with {method}...")
        documents, page_results = classify_pdf(temp_path, settings, log)
        if page_results:
            log_page_results(page_results, log)

        log("💾 Splitting and saving documents locally...")
        saved = save_documents(temp_path, documents, f"uploads/{candidate_id}")
        log(f"Saved locally: {[os.path.basename(path) for _, path in saved]}")

        existing_types = [row[2] for row in get_candidate_documents(candidate_id)]
        uploaded_types = list(existing_types)

        if saved:
            log("☁️ Uploading to Google Drive...")
        else:
            log("❌ Could not classify any pages.")

        for (doc_type, file_path), document in zip(saved, documents):
            if doc_type in existing_types:
                log(f"⏩ {doc_type} already exists — skipping duplicate")
                continue

            link = upload_candidate_document(
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                file_path=file_path,
                doc_type=doc_type
            )
            classified_by, confidence = document_provenance(document, page_results)
            document_id = insert_document(candidate_id, doc_type, file_path, classified_by, confidence)
            uploaded_types.append(doc_type)
            log(f"✅ {doc_type} uploaded → {link}")
            extract_and_store(document_id, candidate_id, document, settings, log)

        # Do all documents belong to this candidate? Uses every stored document, not just this run's.
        flags = replace_flags(candidate_id, check_candidate(candidate_name, get_identity_fields(candidate_id)))
        for f in flags:
            log(f"🚩 {f['type'].replace('_', ' ')} on {f['doc_type']}: {f['detail']}")

        status, found, missing = compute_status(required_docs, uploaded_types)
        if flags:
            # Never report Completed while documents disagree: a person decides first
            status = "Needs Review"
        update_candidate_status(candidate_id, status)
        log(f"📊 Status updated → {status}")
        log(f"Found: {found}")
        log(f"Missing: {missing}")

        return {"status": status, "found": found, "missing": missing, "flags": flags, "error": None}

    except Exception as e:
        log(f"🛑 Pipeline error: {e}")
        return {"status": "Error", "found": [], "missing": [], "flags": [], "error": str(e)}

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
