"""
Follow-up emails: decide what each candidate still owes us, draft the email, check it.

  plan_followup()  the policy, as plain rules: the single source of truth for what to do
  draft_email()    the local LLM writes a candidate-facing email from those facts; code checks
                   the draft; one retry with the problems listed; otherwise a fixed template
  Nothing is sent from here. A person approves each draft in the Outbox page, which then
  only creates a Gmail *draft*; the email is sent by a person from Gmail.
"""
import re
from datetime import date, timedelta

from pydantic import BaseModel

from database import db
from services import validators as v
from services.llm_client import LLMError, chat_json

FRIENDLY = {
    "aadhaar": "Aadhaar card", "pan": "PAN card", "passport": "passport",
    "driving_license": "driving licence", "voter_id": "voter ID card",
    "10th_certificate": "Class 10 certificate", "12th_certificate": "Class 12 certificate",
    "degree_certificate": "degree certificate", "provisional_certificate": "provisional certificate",
    "marksheet": "university marksheet", "offer_letter": "offer letter",
    "appointment_letter": "appointment letter", "experience_letter": "experience letter",
    "relieving_letter": "relieving letter", "payslip": "recent payslip", "form_16": "Form 16",
    "bank_statement": "bank statement", "itr": "income tax return", "cancelled_cheque": "cancelled cheque",
    "police_verification": "police verification certificate", "drug_test": "drug test report",
    "nda": "signed NDA", "bgv_consent": "signed background verification consent form",
    "visa": "visa", "work_permit": "work permit", "electricity_bill": "electricity bill",
    "water_bill": "water bill", "gas_bill": "gas bill", "telephone_bill": "telephone bill",
    "rental_agreement": "rental agreement", "police_clearance": "police clearance certificate",
    "court_record": "court record report",
}

ACTIONS = ["none", "request_documents", "request_clarification", "escalate_to_hr"]

BANNED_WORDS = ["fraud", "fake", "forged", "forgery", "suspicious", "cheat", "lied", "lying", "mismatch"]


def friendly(doc_type):
    return FRIENDLY.get(doc_type, doc_type.replace("_", " "))


def plan_followup(state, settings):
    """
    The policy. state: {"name", "received": [doc types], "flags": [(type, doc_type)], "followups_sent": int}
      1. Already chased max_followups times and still not done -> escalate_to_hr (a person takes over)
      2. Documents disagree                                      -> request_clarification
      3. Required documents missing                              -> request_documents
      4. Otherwise                                               -> none
    """
    required = settings.get("required_docs", ["aadhaar", "pan", "10th_certificate"])
    missing = [d for d in required if d not in state["received"]]
    flagged = sorted({doc_type for _, doc_type in state["flags"]})
    limit = settings.get("max_followups", 2)

    if (missing or flagged) and state["followups_sent"] >= limit:
        action, reason = "escalate_to_hr", f"{state['followups_sent']} follow-ups sent and still incomplete"
    elif flagged:
        action, reason = "request_clarification", f"details differ on: {', '.join(flagged)}"
    elif missing:
        action, reason = "request_documents", f"missing: {', '.join(missing)}"
    else:
        action, reason = "none", "all required documents received and consistent"
    return {"action": action, "reason": reason, "missing": missing, "flagged": flagged}


def deadline(settings, today=None):
    d = (today or date.today()) + timedelta(days=settings.get("followup_deadline_days", 5))
    return d.strftime("%d %B %Y").lstrip("0")


def first_name(name):
    return (name or "").split()[0].title() if name else "Candidate"


# ------------------------------------------------------------------ fixed templates

def template_email(plan, candidate, settings):
    """Always available: used when the LLM is off or its drafts fail the checks twice."""
    company = settings.get("company_name", "our company")
    sign = settings.get("hr_signature", "HR Team")
    due = deadline(settings)

    if plan["action"] == "escalate_to_hr":
        lines = [f"Candidate: {candidate['name']} ({candidate['candidate_id']}, {candidate['email']})",
                 f"Follow-ups already sent: {candidate['followups_sent']}"]
        if plan["missing"]:
            lines.append("Still missing: " + ", ".join(friendly(d) for d in plan["missing"]))
        if plan["flagged"]:
            lines.append("Details differ on: " + ", ".join(friendly(d) for d in plan["flagged"]))
        lines.append("Please contact the candidate directly or decide how to proceed.")
        return {"to": settings.get("hr_email", ""),
                "subject": f"BGV escalation: {candidate['name']} ({candidate['candidate_id']})",
                "body": "\n".join(lines)}

    items = [friendly(d) for d in plan["flagged"]] + [friendly(d) for d in plan["missing"]]
    body = [f"Dear {first_name(candidate['name'])},", ""]
    if plan["flagged"]:
        body.append("Thank you for sending your documents. While checking them, we could not match some "
                    "details with our records. Could you please check and resend the following, making sure "
                    "they are your own documents and show your name and date of birth clearly:")
    else:
        body.append(f"Thank you for your interest in joining {company}. To complete your background "
                    "verification, we still need the following documents:")
    body += [f"- {item}" for item in items]
    body += ["", f"Please reply to this email with the documents by {due}.",
             "If you have any questions, just reply to this email.", "", "Regards,", sign, company]
    return {"to": candidate["email"], "subject": f"Documents needed for your background verification - {company}",
            "body": "\n".join(body)}


# ------------------------------------------------------------------ checks on any draft

def check_draft(draft, plan, candidate, settings, private_values=()):
    """
    Plain-code rules every candidate email must pass. Returns a list of problems (empty = OK).
    private_values: names/DOBs read from flagged documents, which must never be repeated.
    """
    body, subject = draft.get("body", ""), draft.get("subject", "")
    text = f"{subject}\n{body}".lower()
    problems = []

    requested = plan["flagged"] + plan["missing"]
    for d in requested:
        if friendly(d).lower() not in text:
            problems.append(f"does not ask for the {friendly(d)}")
    for d, name in FRIENDLY.items():
        if d not in requested and re.search(rf"\b{re.escape(name.lower())}\b", text) \
                and not any(name.lower() in friendly(r).lower() for r in requested):
            problems.append(f"mentions the {name}, which was not requested")

    if first_name(candidate["name"]).lower() not in body.lower()[:200]:
        problems.append("does not greet the candidate by first name")
    if deadline(settings).lower() not in text:
        problems.append(f"does not give the deadline {deadline(settings)}")
    for word in BANNED_WORDS:
        if re.search(rf"\b{word}", text):
            problems.append(f"uses the word '{word}' (accusing or internal wording)")
    pan_like = rf"\b{v.ID_FORMATS['pan'].pattern}\b"
    if re.search(r"\d{6,}", re.sub(r"[\s-]", "", body)) or re.search(pan_like, body.upper()):
        problems.append("contains an ID number")
    for value in private_values:
        if value and value.lower() in text:
            problems.append("repeats a name or date from a flagged document")
    if len(body) > 1500:
        problems.append("is too long")
    return problems


# ------------------------------------------------------------------ LLM draft

class EmailDraft(BaseModel):
    subject: str
    body: str


def llm_messages(plan, candidate, settings):
    company = settings.get("company_name", "our company")
    facts = [f"Candidate first name: {first_name(candidate['name'])}",
             f"Company: {company}",
             f"Deadline: {deadline(settings)}",
             f"Sign off as: {settings.get('hr_signature', 'HR Team')}, {company}"]
    if plan["flagged"]:
        facts.append("Documents to check and resend (details on them could not be matched with our records): "
                     + "; ".join(friendly(d) for d in plan["flagged"]))
    if plan["missing"]:
        facts.append("Documents still missing: " + "; ".join(friendly(d) for d in plan["missing"]))

    system = ("You write short, warm, professional emails from an HR team to a job candidate about "
              "background-verification documents.\n"
              "Rules: use only the facts given. Name every document exactly as written in the facts and no "
              "other documents. State the deadline exactly as given. Never include ID numbers, dates of birth "
              "or anyone else's name. Never accuse the candidate or use words like fraud, fake or mismatch; "
              "if details could not be matched, ask politely to check and resend. Under 150 words.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(facts)}]


def draft_email(plan, candidate, settings, private_values=()):
    """
    Returns {"to", "subject", "body", "source", "attempts", "problems"}.
    source: "llm" (first try), "llm_retry" (passed after feedback), "template" (fallback).
    """
    if plan["action"] == "none":
        return None
    if plan["action"] == "escalate_to_hr" or settings.get("classifier") != "llm":
        draft = template_email(plan, candidate, settings)
        return {**draft, "source": "template", "attempts": 0, "problems": []}

    messages = llm_messages(plan, candidate, settings)
    seen, attempts = [], 0
    for attempt in (1, 2):
        try:
            answer, _ = chat_json(messages, EmailDraft, settings, num_predict=500)
            attempts = attempt
        except LLMError as e:
            seen.append(f"LLM unavailable: {e}")
            break
        draft = {"to": candidate["email"], "subject": answer.subject.strip(), "body": answer.body.strip()}
        problems = check_draft(draft, plan, candidate, settings, private_values)
        if not problems:
            return {**draft, "source": "llm" if attempt == 1 else "llm_retry", "attempts": attempt,
                    "problems": seen}
        seen += problems
        # Feed the problems back once, as the user turn, and ask for a corrected draft
        messages = messages + [
            {"role": "assistant", "content": answer.model_dump_json()},
            {"role": "user", "content": "Your draft broke these rules: " + "; ".join(problems)
                                        + ". Rewrite it following every rule."},
        ]

    draft = template_email(plan, candidate, settings)
    return {**draft, "source": "template", "attempts": attempts, "problems": seen}


# ------------------------------------------------------------------ the app's Outbox flow

def candidate_state(candidate_id, name):
    """What we know about one candidate, read from the database."""
    flags = [(t, d) for t, d, _ in db.get_open_flags(candidate_id)]
    flagged = {d for _, d in flags}
    # Names read from flagged documents may be someone else's: never put them in an email
    private = [value for doc_type, field, value, *_ in db.get_extracted_fields(candidate_id)
               if doc_type in flagged and field in ("name", "dob") and value and value != name]
    return {"name": name,
            "received": sorted({row[2] for row in db.get_candidate_documents(candidate_id)}),
            "flags": flags,
            "followups_sent": db.count_followups(candidate_id, "approved")}, private


def prepare_followups(settings, log=print):
    """Drafts one follow-up per candidate that needs one, into the Outbox (status pending)."""
    waiting = {row[1] for row in db.get_followups("pending")}
    created = []
    for candidate_id, name, email, _, status in db.get_all_candidates():
        if candidate_id in waiting:
            continue  # a person has not decided on the last draft yet
        state, private = candidate_state(candidate_id, name)
        plan = plan_followup(state, settings)
        if plan["action"] == "none":
            continue
        candidate = {"candidate_id": candidate_id, "name": name, "email": email,
                     "followups_sent": state["followups_sent"]}
        draft = draft_email(plan, candidate, settings, private)
        followup_id = db.insert_followup(candidate_id, plan["action"], plan["reason"], draft["to"],
                                         draft["subject"], draft["body"], draft["source"])
        log(f"📝 {candidate_id}: {plan['action']} ({plan['reason']}) — written by {draft['source']}")
        created.append(followup_id)
    return created


def approve_followup(followup_id, subject, body, gmail_service):
    """A person approved (and maybe edited) the draft: create it as a Gmail draft. Nothing is sent."""
    from services.gmail_service import create_draft

    row = next(r for r in db.get_followups("pending") if r[0] == followup_id)
    draft_id = create_draft(gmail_service, row[4], subject, body)
    db.decide_followup(followup_id, "approved", subject, body, draft_id)
    return draft_id


def reject_followup(followup_id):
    db.decide_followup(followup_id, "rejected")


def check_followup_row(row, settings):
    """Re-runs the checks on a stored draft as the person sees it, including their edits."""
    followup_id, candidate_id, action, _, to_email, subject, body, *_ = row
    if action == "escalate_to_hr":
        return []
    name = next((c[1] for c in db.get_all_candidates() if c[0] == candidate_id), "")
    state, private = candidate_state(candidate_id, name)
    plan = plan_followup(state, settings)
    candidate = {"candidate_id": candidate_id, "name": name, "email": to_email}
    return check_draft({"subject": subject, "body": body}, plan, candidate, settings, private)
