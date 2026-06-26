from services.gmail_service import get_gmail_service, get_attachment_for_candidate

service = get_gmail_service()

candidate_email = "satwikgupta987@gmail.com"

data = get_attachment_for_candidate(service, candidate_email)

if data:
    with open("test_output.pdf", "wb") as f:
        f.write(data)
    print("✅ Saved test_output.pdf — open it and confirm it's the right candidate's document")
else:
    print("❌ No matching email/attachment found for that address")