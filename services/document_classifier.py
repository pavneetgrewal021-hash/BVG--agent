import fitz
import pytesseract
from PIL import Image
import io

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def extract_text_from_pdf(pdf_path):
    """Try digital text first. If empty, use OCR on scanned pages."""
    doc = fitz.open(pdf_path)
    text = ""

    for page in doc:
        page_text = page.get_text()
        text += page_text

   
    if len(text.strip()) < 20:
        text = ""
        for page in doc:
            
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
           
            ocr_text = pytesseract.image_to_string(img, lang="eng")
            text += ocr_text

    return text.lower()


def classify_document(pdf_path):
    """Classify PDF as aadhaar, pan, 10th_certificate, or unknown."""
    text = extract_text_from_pdf(pdf_path)

    aadhaar_keywords = [
        "aadhaar", "aadhar", "uidai",
        "unique identification authority of india",
        "government of india", "enrolment no"
    ]

    pan_keywords = [
        "income tax department",
        "permanent account number",
        "pan", "govt. of india"
    ]

    tenth_keywords = [
        "secondary school", "matriculation",
        "10th", "class x", "cbse", "icse",
        "board of secondary education",
        "secondary education", "high school certificate"
    ]

    if any(k in text for k in aadhaar_keywords):
        return "aadhaar"

    if any(k in text for k in pan_keywords):
        return "pan"

    if any(k in text for k in tenth_keywords):
        return "10th_certificate"

    return "unknown"

import pytesseract
from PIL import Image
import io

DOC_KEYWORDS = {
   
    "aadhaar":          ["aadhaar", "uidai", "unique identification authority", "enrolment no"],
    "pan":              ["income tax department", "permanent account number"],
    "passport":         ["passport", "republic of india", "nationality", "place of birth", "date of expiry"],
    "driving_license":  ["driving licence", "driving license", "transport authority", "motor vehicles"],
    "voter_id":         ["election commission", "electors photo identity", "epic no", "voter"],

   
    "10th_certificate": ["secondary school", "matriculation", "class x", "cbse", "icse", "board of secondary education", "high school"],
    "12th_certificate": ["higher secondary", "class xii", "class 12", "intermediate certificate", "senior secondary"],
    "degree_certificate": ["bachelor of", "b.tech", "b.e.", "b.sc", "b.com", "b.a.", "university", "degree certificate", "convocation"],
    "provisional_certificate": ["provisional certificate", "provisionally passed"],
    "marksheet":        ["marksheet", "mark sheet", "semester", "consolidated marks", "grade sheet"],

  
    "offer_letter":     ["offer letter", "we are pleased to offer", "offer of employment", "joining date"],
    "appointment_letter": ["appointment letter", "letter of appointment"],
    "experience_letter": ["experience letter", "to whomsoever it may concern", "worked with us", "employment with"],
    "relieving_letter": ["relieving letter", "relieved from", "last working day"],
    "payslip":          ["payslip", "pay slip", "salary slip", "basic salary", "net pay", "gross salary", "pf deduction"],
    "form_16":          ["form 16", "tds certificate", "tax deducted at source", "assessment year"],


    "bank_statement":   ["bank statement", "account statement", "opening balance", "closing balance", "transaction date"],
    "itr":              ["income tax return", "itr", "acknowledgement number", "assessment year", "total income"],
    "cancelled_cheque": ["cancelled", "account number", "ifsc", "micr"],

  
    "police_verification": ["police verification", "character certificate", "no criminal"],
    "drug_test":           ["drug test", "substance abuse", "urine test", "negative for"],
    "nda":                 ["non disclosure", "nda", "confidentiality agreement"],
    "bgv_consent":         ["background verification consent", "bgv consent", "consent form"],


    "visa":             ["visa", "embassy", "consulate", "visa category"],
    "work_permit":      ["work permit", "employment authorization"],

   
    "electricity_bill":   ["electricity bill", "electric supply", "power bill", "units consumed", "meter number"],
    "water_bill":         ["water bill", "water supply", "water charges", "municipal water"],
    "gas_bill":           ["gas bill", "piped natural gas", "png bill", "gas supply"],
    "telephone_bill":     ["telephone bill", "broadband bill", "airtel", "jio", "bsnl", "vodafone", "postpaid bill"],
    "rental_agreement":   ["rental agreement", "rent agreement", "lease agreement", "tenant", "landlord", "monthly rent"],
    "bank_statement":     ["bank statement", "account statement", "opening balance", "closing balance", "transaction date"],

    
    "police_clearance":   ["police clearance", "clearance certificate", "no criminal record", "character certificate", "good conduct"],
    "court_record":       ["court record", "criminal record", "fir", "first information report", "judicial"],
}

def extract_page_texts(pdf_path):
    """Text of every page: the PDF's own text layer, or Tesseract OCR when a page has none."""
    doc = fitz.open(pdf_path)
    texts = []

    for page in doc:
        text = page.get_text().strip()

        if not text:
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img)

        texts.append(text)

    doc.close()
    return texts


def keyword_classify_text(text):
    """First doc type whose keywords appear in the text, else 'unknown'."""
    text = text.lower()

    for doc_type, keywords in DOC_KEYWORDS.items():
        if any(k in text for k in keywords):
            return doc_type

    return "unknown"


def classify_pdf_pages(pdf_path, page_texts=None):
    """Goes page by page. Returns {doc_type: [page_indices]}"""
    if page_texts is None:
        page_texts = extract_page_texts(pdf_path)

    page_results = {}
    for i, text in enumerate(page_texts):
        page_results.setdefault(keyword_classify_text(text), []).append(i)

    return page_results


def save_split_documents(pdf_path, page_results, output_dir):
    """Saves each matched doc type as its own PDF. Returns {doc_type: filepath}"""
    import os
    os.makedirs(output_dir, exist_ok=True)

    src = fitz.open(pdf_path)
    saved = {}

    for doc_type, pages in page_results.items():
        if doc_type == "unknown":
            continue

        new_doc = fitz.open()
        for p in pages:
            new_doc.insert_pdf(src, from_page=p, to_page=p)

        filepath = os.path.join(output_dir, f"{doc_type}.pdf")
        new_doc.save(filepath)
        new_doc.close()
        saved[doc_type] = filepath

    src.close()
    return saved

def write_temp_pdf(pdf_bytes):
    """Writes bytes to a fresh temp file and returns its path. The caller must delete it."""
    import os
    import tempfile

    # A fresh file per run, so two users processing at once can't overwrite each other's PDF
    fd, temp_path = tempfile.mkstemp(prefix="bgv_", suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(pdf_bytes)
    return temp_path


def save_documents(pdf_path, documents, output_dir):
    """Saves each document ({"doc_type", "pages"}) as its own PDF.
    Repeated types get a suffix (payslip.pdf, payslip_2.pdf). Returns [(doc_type, filepath)]."""
    import os
    os.makedirs(output_dir, exist_ok=True)

    src = fitz.open(pdf_path)
    saved, counts = [], {}

    for document in documents:
        doc_type = document["doc_type"]
        counts[doc_type] = counts.get(doc_type, 0) + 1
        suffix = "" if counts[doc_type] == 1 else f"_{counts[doc_type]}"

        new_doc = fitz.open()
        for p in document["pages"]:
            new_doc.insert_pdf(src, from_page=p, to_page=p)

        filepath = os.path.join(output_dir, f"{doc_type}{suffix}.pdf")
        new_doc.save(filepath)
        new_doc.close()
        saved.append((doc_type, filepath))

    src.close()
    return saved


def classify_pdf_from_bytes(pdf_bytes, temp_path=None):
    """Takes raw PDF bytes (e.g. from Gmail), writes a temp file, classifies it.
    The caller must delete temp_path when done."""
    import os

    if temp_path is None:
        temp_path = write_temp_pdf(pdf_bytes)
    else:
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)

    try:
        page_results = classify_pdf_pages(temp_path)
    except Exception:
        os.remove(temp_path)  # corrupt PDF: don't leave candidate data on disk
        raise
    return page_results, temp_path