from services.drive_service import upload_candidate_document

link = upload_candidate_document(
    candidate_id="1",
    candidate_name="Puja",
    file_path="uploads/C101/aadhaar.pdf",
    doc_type="aadhaar",
    run_suffix="2_time"
)
print("Uploaded successfully! Target link:", link)