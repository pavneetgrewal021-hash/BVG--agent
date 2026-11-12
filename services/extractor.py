"""
Field extraction: name, date of birth, document number and issue date.

Three methods, compared in eval/run_extraction_eval.py:
  regex   rules only (the baseline, no model)
  llm     the local LLM's raw answer
  hybrid  the LLM's answer checked by code: every value must be printed on the
          page and pass its format rules, otherwise it is dropped or replaced by
          a regex match. This is what the app uses.
"""
import re
from typing import Optional

from pydantic import BaseModel

from services import validators as v
from services.llm_client import LLMError, chat_json

# v1: prompt as below. Checks v2: gaps left by the model are filled from regex rules
# when the regex value passes the same checks.
PROMPT_VERSION = "v1"
CHECKS_VERSION = "v2"
FIELDS = ["name", "dob", "doc_number", "issue_date"]
IDENTITY_TYPES = set(v.ID_FORMATS)

SYSTEM_PROMPT = """You extract fields from one Indian document a job candidate sent for background verification.

Copy values exactly as printed. If a field is not printed on the document, return null.
Never guess, calculate or reformat a value from other information.

- name: full name of the person the document is about (the candidate), not a parent, employer
  or official. For a passport, given name(s) followed by surname.
- dob: that person's date of birth, as YYYY-MM-DD.
- doc_number: the document's own identifying number (Aadhaar number, PAN, passport number,
  licence number, EPIC number, roll number, certificate or serial number, employee ID).
- issue_date: the date the document was issued or dated (date of issue, allotment, letter
  date, convocation date), as YYYY-MM-DD. Not a date of birth, joining, expiry or exam date."""


class ExtractedFields(BaseModel):
    name: Optional[str]
    dob: Optional[str]
    doc_number: Optional[str]
    issue_date: Optional[str]


# ------------------------------------------------------------------ regex baseline

NAME_PATTERNS = [
    r"(?:^|\n)\s*(?:Name|Name of Candidate|Elector's Name|Employee Name|Account Holder|Applicant|Candidate)"
    r"\s*[:\n]\s*([A-Za-z][A-Za-z .]+?)(?:\s{2,}|\n|$)",
    r"(?:certify that|Dear)\s+([A-Za-z][A-Za-z .]+?)(?:,|\n|\s{2,}|$)",
]
DOB_PATTERN = r"(?:DOB|Date of Birth)\s*[:\n]?\s*(\d{2}/\d{2}/\d{4})"
ISSUE_PATTERN = (r"(?:Date of Issue|Issue Date|Date of Allotment|Issued on|Download Date|Dated|Date)"
                 r"\s*[:\n]?\s*(\d{2}/\d{2}/\d{4})")


def regex_extract(doc_type, text):
    fields = dict.fromkeys(FIELDS)
    for pattern in NAME_PATTERNS:
        m = re.search(pattern, text)
        if m:
            fields["name"] = m.group(1).strip()
            break
    m = re.search(DOB_PATTERN, text)
    if m:
        fields["dob"] = m.group(1)
    m = re.search(ISSUE_PATTERN, text)
    if m:
        fields["issue_date"] = m.group(1)
    numbers = v.find_id_numbers(doc_type, text)
    if numbers:
        fields["doc_number"] = numbers[0]
    return fields


# ------------------------------------------------------------------ LLM

def llm_extract(doc_type, text, settings):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Document type: {doc_type}\n<document>\n{text[:6000]}\n</document>"},
    ]
    answer, usage = chat_json(messages, ExtractedFields, settings, num_predict=200)
    return answer.model_dump(), usage


# ------------------------------------------------------------------ checks

def check_fields(doc_type, raw, text):
    """
    Applies the code checks to one set of extracted values.
    Returns {field: {"value", "source", "status", "note"}} where status is
      ok       printed on the page and passes its rules
      invalid  printed on the page but breaks a rule (kept, shown as a warning)
      dropped  not printed on the page or not a real date: treated as a model invention
      missing  no value
    """
    out = {}

    name = raw.get("name")
    if name and v.name_on_page(name, text):
        out["name"] = {"value": " ".join(name.split()), "status": "ok"}
    elif name:
        out["name"] = {"value": None, "status": "dropped", "note": f"'{name}' is not on the page"}

    for field in ("dob", "issue_date"):
        value = raw.get(field)
        d = v.parse_date(value)
        if value and d is None:
            out[field] = {"value": None, "status": "dropped", "note": f"'{value}' is not a date"}
        elif d and not v.date_on_page(d, text):
            out[field] = {"value": None, "status": "dropped",
                          "note": f"{d.isoformat()} is not printed on the page (invented or day/month swapped)"}
        elif d:
            problems = v.check_dob(d) if field == "dob" else []
            out[field] = {"value": d.isoformat(), "status": "invalid" if problems else "ok",
                          "note": "; ".join(problems) or None}

    number = raw.get("doc_number")
    if doc_type in IDENTITY_TYPES:
        holder = out.get("name", {}).get("value")
        candidates = [n for n in v.find_id_numbers(doc_type, text) if not v.check_id_number(doc_type, n)]
        if number and v.number_on_page(number, text) and not v.check_id_number(doc_type, number, holder):
            out["doc_number"] = {"value": v.compact(number), "status": "ok"}
        elif len(candidates) == 1:
            # The model's number is missing or fails the rules, but the page has exactly one valid one
            out["doc_number"] = {"value": candidates[0], "status": "ok", "source": "regex",
                                 "note": f"model said {number!r}; replaced by the only valid number on the page"}
            problems = v.check_id_number(doc_type, candidates[0], holder)
            if problems:
                out["doc_number"].update(status="invalid", note="; ".join(problems))
        elif number and v.number_on_page(number, text):
            out["doc_number"] = {"value": v.compact(number), "status": "invalid",
                                 "note": "; ".join(v.check_id_number(doc_type, number, holder))}
        elif number:
            out["doc_number"] = {"value": None, "status": "dropped", "note": f"'{number}' is not on the page"}
    elif number:
        on_page = v.number_on_page(number, text)
        out["doc_number"] = {"value": v.compact(number) if on_page else None,
                             "status": "ok" if on_page else "dropped",
                             "note": None if on_page else f"'{number}' is not on the page"}

    for field in FIELDS:
        out.setdefault(field, {"value": None, "status": "missing"})
        out[field].setdefault("source", "llm")
        out[field].setdefault("note", None)
    return out


def fill_gaps_from_regex(checked, doc_type, text):
    """
    Where the model gave nothing usable, take the regex value if it passes the same checks.
    Regex rules never produced a wrong value on the dev set, so they are a safe second source.
    """
    from_regex = check_fields(doc_type, regex_extract(doc_type, text), text)
    for field in FIELDS:
        if checked[field]["status"] in ("missing", "dropped") and from_regex[field]["status"] == "ok":
            note = checked[field]["note"]
            checked[field] = {**from_regex[field], "source": "regex",
                              "note": f"filled by regex rules ({note})" if note else "filled by regex rules"}
    return checked


def extract_document(doc_type, text, settings, method="hybrid"):
    """
    Returns {"fields": {field: {...}}, "raw": {...}, "method", "error", "seconds"}.
    Falls back to regex when the LLM is unavailable.
    """
    if method == "regex" or settings.get("classifier") != "llm":
        raw = regex_extract(doc_type, text)
        fields = check_fields(doc_type, raw, text)
        for f in fields.values():
            f["source"] = "regex"
        return {"fields": fields, "raw": raw, "method": "regex", "error": None, "seconds": 0.0}

    try:
        raw, usage = llm_extract(doc_type, text, settings)
    except LLMError as e:
        result = extract_document(doc_type, text, settings, method="regex")
        result.update(method="regex_fallback", error=str(e))
        return result

    if method == "llm":  # raw model answer, for the evaluation only
        fields = {f: {"value": raw[f], "status": "unchecked", "source": "llm", "note": None} for f in FIELDS}
    else:
        fields = fill_gaps_from_regex(check_fields(doc_type, raw, text), doc_type, text)
    return {"fields": fields, "raw": raw, "method": method, "error": None, "seconds": usage["seconds"]}
