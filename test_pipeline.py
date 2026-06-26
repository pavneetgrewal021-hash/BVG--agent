from services.gmail_service import get_gmail_service, get_attachment_for_candidate
from services.document_classifier import classify_pdf_from_bytes, save_split_documents
from services.drive_service import upload_candidate_document
from database.db import insert_document, update_candidate_status, get_candidate_documents


candidate_id    = "C101"
candidate_name  = "Satwik"
candidate_email = "satwikgupta987@gmail.com"

REQUIRED_DOCS = ["aadhaar", "pan", "10th_certificate"]


print(f"\n📧 Fetching attachment from Gmail for {candidate_email}...")
service = get_gmail_service()
data = get_attachment_for_candidate(service, candidate_email)

if not data:
    print("❌ No attachment found for this candidate")
    exit()

print("✅ Attachment fetched")


print("\n🔍 Classifying pages...")
page_results, temp_path = classify_pdf_from_bytes(data)
print("Page classification:", page_results)


print("\n💾 Saving split documents locally...")
output_dir = f"uploads/{candidate_id}"
saved = save_split_documents(temp_path, page_results, output_dir)
print("Saved files:", saved)



if not saved:
    print("❌ No documents were saved — check classifier output")
    exit()

print("\n🔎 Checking for existing documents in DB...")
existing_docs = get_candidate_documents(candidate_id)
existing_types = [row[2] for row in existing_docs]  
print("Already in DB:", existing_types)


print("\n☁️  Uploading to Google Drive...")
uploaded_types = list(existing_types)  

for doc_type, file_path in saved.items():

    if doc_type == "unknown":
        print(f"  ⚠️  Skipping unknown doc: {file_path}")
        continue

    if doc_type in existing_types:
        print(f"  ⏩ {doc_type} already exists in DB — skipping duplicate")
        continue

    print(f"  ⬆️  Uploading {doc_type}...")
    link = upload_candidate_document(
        candidate_id=candidate_id,
        candidate_name=candidate_name,
        file_path=file_path,
        doc_type=doc_type
    )

    insert_document(candidate_id, doc_type, file_path)
    uploaded_types.append(doc_type)
    print(f"  ✅ {doc_type} uploaded → {link}")


print("\n📊 Calculating status...")
found_required = [doc for doc in REQUIRED_DOCS if doc in uploaded_types]
missing        = [doc for doc in REQUIRED_DOCS if doc not in uploaded_types]

if len(found_required) == len(REQUIRED_DOCS):
    status = "Completed"
elif len(found_required) > 0:
    status = "Partial"
else:
    status = "Failed"

update_candidate_status(candidate_id, status)


print("\n" + "="*50)
print(f"  Candidate : {candidate_id} - {candidate_name}")
print(f"  Status    : {status}")
print(f"  Found     : {found_required}")
print(f"  Missing   : {missing}")
print("="*50)