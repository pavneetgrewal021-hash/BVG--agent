"""
Page classification with a local LLM, falling back to the keyword rules.

classify_pdf() returns the documents found in a PDF, each as a type plus its
pages. Unlike the keyword classifier, the LLM also says whether a page
continues the previous one, so two payslips stay two documents and the back
of a degree certificate stays with its front.
"""
from typing import Literal

from pydantic import BaseModel, Field

from services.document_classifier import DOC_KEYWORDS, extract_page_texts, keyword_classify_text
from services.llm_client import LLMError, chat_json

# v1: first version.
# v2: continuation only when the model's own type agrees with the previous page (v1 copied the
#     previous type and spread errors); sharper education descriptions; evidence = title/issuer.
PROMPT_VERSION = "v2"

DOC_TYPES = list(DOC_KEYWORDS) + ["unknown"]

DESCRIPTIONS = {
    "aadhaar": "Aadhaar card (front or back) or e-Aadhaar letter issued by UIDAI",
    "pan": "PAN card or e-PAN issued by the Income Tax Department",
    "passport": "Indian passport data page or its last (address) page",
    "driving_license": "driving licence issued by a transport department / licensing authority",
    "voter_id": "voter ID / EPIC card from the Election Commission",
    "10th_certificate": "Class 10 school board certificate or marks statement: CBSE 'Secondary School "
                        "Examination', ICSE, matriculation (even when it lists marks)",
    "12th_certificate": "Class 12 school board certificate or marks statement: CBSE 'Senior School "
                        "Certificate Examination', ISC, senior/higher secondary, intermediate (even when it lists marks)",
    "degree_certificate": "final degree certificate from a university that confers or awards a degree",
    "provisional_certificate": "provisional certificate saying the degree is passed but not yet formally awarded",
    "marksheet": "university or college semester grade card / statement of marks (not school board certificates)",
    "offer_letter": "job offer letter or letter of intent from an employer",
    "appointment_letter": "appointment letter confirming employment terms",
    "experience_letter": "experience certificate or 'to whomsoever it may concern' service letter",
    "relieving_letter": "letter relieving an employee from service after resignation",
    "payslip": "monthly payslip / salary slip",
    "form_16": "Form 16 TDS certificate (Part A or Part B) from an employer",
    "bank_statement": "bank account statement listing transactions",
    "itr": "income tax return or ITR-V acknowledgement",
    "cancelled_cheque": "a cancelled cheque leaf",
    "police_verification": "police verification / character and antecedents report about the candidate",
    "drug_test": "drug or substance test report",
    "nda": "non-disclosure or confidentiality agreement",
    "bgv_consent": "background verification consent or authorisation form signed by the candidate",
    "visa": "visa issued by an embassy or consulate",
    "work_permit": "work permit or employment authorisation",
    "electricity_bill": "electricity bill",
    "water_bill": "water bill",
    "gas_bill": "gas / PNG bill",
    "telephone_bill": "telephone, mobile or broadband bill",
    "rental_agreement": "rent or lease agreement",
    "police_clearance": "Police Clearance Certificate (PCC) for passport or emigration purposes",
    "court_record": "court record or litigation search report about the candidate",
    "unknown": "not a verification document (cover letter, email, blank page) or impossible to tell",
}

SYSTEM_PROMPT = f"""You classify one page of a PDF a job candidate sent for background verification.

Rules:
1. Classify by what the page IS, not by documents it mentions. A letter or form that lists or
   asks for documents (for example "please bring your Aadhaar and PAN") is that letter or form.
2. continues_previous_page is true only when this page is the back side, a later page or an
   annexure of the SAME document as the previous page. A new document with its own title is not
   a continuation, even if it is the same kind of document.
3. evidence: copy the document's title or issuing authority exactly as written (at most 10 words).
   Never quote watermarks, footers or page numbers.
4. confidence: your probability (0 to 1) that doc_type is correct.

Document types:
""" + "\n".join(f"- {t}: {d}" for t, d in DESCRIPTIONS.items())

MAX_PAGE_CHARS = 6000  # ~2000 tokens, leaves room for the prompt in a 4096-token context


class PageClassification(BaseModel):
    # Field order is generation order: quoting evidence first makes the model look before it labels
    evidence: str
    doc_type: Literal[tuple(DOC_TYPES)]
    continues_previous_page: bool
    confidence: float = Field(ge=0, le=1)


def normalise(text):
    return " ".join(text.lower().split())


def build_messages(text, page_number, total_pages, previous):
    if previous is None:
        context = "This is the first page of the PDF."
    else:
        context = (f"The previous page was classified as {previous['doc_type']} and begins:\n"
                   f"\"{normalise(previous['text'])[:300]}\"")
    user = (f"{context}\n\nPage {page_number} of {total_pages}:\n<page>\n"
            f"{text[:MAX_PAGE_CHARS]}\n</page>")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def classify_pages(page_texts, settings, log=print):
    """One result dict per page. Uses the LLM, or the keyword rules for any page where it fails."""
    results = []
    previous = None
    failures_in_a_row = 0

    for i, text in enumerate(page_texts):
        result = {"page": i, "text": text, "method": "llm", "confidence": None, "evidence": None,
                  "evidence_found": None, "continues_previous_page": False, "seconds": None, "error": None,
                  # Measured on the eval set: every LLM mistake was on a page where it disagreed with the
                  # keyword rules, so disagreement is shown to the user as a hint to review that page.
                  "keyword_type": keyword_classify_text(text)}
        try:
            # Circuit breaker: after 2 failures in a row (server down?) stop waiting on the LLM
            if failures_in_a_row >= 2:
                raise LLMError("skipped after repeated failures")
            answer, usage = chat_json(build_messages(text, i + 1, len(page_texts), previous),
                                      PageClassification, settings)
            failures_in_a_row = 0
            # Trust "continues" only when the model's own label agrees with the previous page.
            # Copying the previous label instead let one mistake spread down the PDF (prompt v1).
            continues = (answer.continues_previous_page and previous is not None
                         and answer.doc_type == previous["doc_type"])
            result.update(
                doc_type=answer.doc_type,
                continues_previous_page=continues,
                confidence=answer.confidence,
                evidence=answer.evidence,
                # A quote that is not on the page is a sign the model made something up
                evidence_found=normalise(answer.evidence) in normalise(text),
                seconds=usage["seconds"],
            )
        except LLMError as e:
            failures_in_a_row += 1
            result.update(doc_type=result["keyword_type"], method="keyword_fallback", error=str(e))
            log(f"⚠️ Page {i + 1}: LLM unavailable ({e}) — used keyword rules")

        results.append(result)
        previous = result

    return results


def group_into_documents(page_results):
    """Consecutive pages form one document when a page continues the one before it."""
    documents = []
    for r in page_results:
        if r["doc_type"] == "unknown":
            continue
        if r["continues_previous_page"] and documents and documents[-1]["pages"][-1] == r["page"] - 1:
            documents[-1]["pages"].append(r["page"])
        else:
            documents.append({"doc_type": r["doc_type"], "pages": [r["page"]]})
    return documents


def keyword_documents(page_texts):
    """The original behaviour: every page of one type merged into one document."""
    by_type = {}
    for i, text in enumerate(page_texts):
        doc_type = keyword_classify_text(text)
        if doc_type != "unknown":
            by_type.setdefault(doc_type, []).append(i)
    return [{"doc_type": t, "pages": p} for t, p in by_type.items()]


def classify_pdf(pdf_path, settings, log=print):
    """
    Returns (documents, page_results).
      documents    : [{"doc_type", "pages"}], what the pipeline saves and uploads
      page_results : per-page details (method, confidence, evidence), None for the keyword classifier
    """
    page_texts = extract_page_texts(pdf_path)

    if settings.get("classifier", "keyword") != "llm":
        return keyword_documents(page_texts), None

    page_results = classify_pages(page_texts, settings, log)
    return group_into_documents(page_results), page_results
