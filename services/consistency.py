"""
Cross-document consistency checks: does every document belong to the same person?

Plain code, no model. Two kinds of flag:
  name_mismatch  a document's name is not a plausible way of writing the candidate's name
  dob_mismatch   a document's date of birth differs from the candidate's other documents

The hard part is NOT flagging legitimate differences. Indian documents routinely print
the same person as "Joseph Mohan Nair", "Joseph Nair", "Joseph M. Nair", "J. Nair" or
"NAIR JOSEPH". A naive exact comparison flags all of those; see names_compatible().
"""
import re
from collections import Counter
from difflib import SequenceMatcher

from services.validators import normalise_name, parse_date

# When documents disagree evenly on a DOB, trust the stronger identity documents first
DOB_AUTHORITY = ["aadhaar", "passport", "pan", "10th_certificate", "driving_license", "voter_id"]

RELATION = re.compile(r"\b[SDWC]\s*/\s*O\b.*", re.IGNORECASE)  # "Neha Patel, D/O Imran Patel"


def name_tokens(name):
    return normalise_name(RELATION.sub("", name or "")).split()


def tokens_match(a, b):
    """'r' matches 'rohan' (initial); 'harpret' matches 'harpreet' (one OCR slip); 'rohan' != 'rahul'."""
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    return min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.88


def names_compatible(reference, other):
    """
    (ok, reason). The other name may drop middle names, shorten names to initials and change
    word order, but every word it does print must fit a different word of the reference, and
    it must contain the surname and the first name (or their initials).
    """
    ref, doc = name_tokens(reference), name_tokens(other)
    if not ref or not doc:
        return True, "nothing to compare"

    unused = list(range(len(ref)))
    for word in doc:
        # Prefer an exact or full-word match over an initial, so "r sharma" maps r->rohan, not r->...
        options = sorted((i for i in unused if tokens_match(word, ref[i])),
                         key=lambda i: (ref[i] != word, len(word) == 1 or len(ref[i]) == 1))
        if not options:
            return False, f"'{word}' does not fit any part of '{reference}'"
        unused.remove(options[0])

    if len(ref) - 1 in unused:
        return False, f"surname '{ref[-1]}' is missing"
    if 0 in unused:
        return False, f"first name '{ref[0]}' is missing"
    return True, "compatible"


def exact_names_match(reference, other):
    """The naive baseline: identical after case and spacing are ignored."""
    ok = normalise_name(reference) == normalise_name(other)
    return ok, "identical" if ok else "not identical"


def check_candidate(reference_name, documents, matcher=names_compatible):
    """
    documents: [{"doc_type", "name", "dob"}] with values as extracted (None if not read).
    Returns flags: [{"type", "doc_type", "detail"}].
    """
    flags = []
    same_person = []

    for d in documents:
        if not d.get("name"):
            same_person.append(d)
            continue
        ok, reason = matcher(reference_name, d["name"])
        if ok:
            same_person.append(d)
        else:
            flags.append({"type": "name_mismatch", "doc_type": d["doc_type"],
                          "detail": f"'{d['name']}' vs candidate '{reference_name}': {reason}"})

    # A document that belongs to someone else does not get a vote on the DOB
    dated = [(d, parse_date(d.get("dob"))) for d in same_person]
    dated = [(d, dob) for d, dob in dated if dob]
    if len(dated) >= 2:
        counts = Counter(dob for _, dob in dated)
        top = max(counts.values())
        tied = {dob for dob, n in counts.items() if n == top}
        if len(tied) == 1:
            reference_dob = tied.pop()
        else:
            ranked = sorted(dated, key=lambda x: DOB_AUTHORITY.index(x[0]["doc_type"])
                            if x[0]["doc_type"] in DOB_AUTHORITY else len(DOB_AUTHORITY))
            reference_dob = ranked[0][1]
        source = "most documents" if top > 1 and len([1 for n in counts.values() if n == top]) == 1 else \
            next(d["doc_type"] for d, dob in dated if dob == reference_dob)
        for d, dob in dated:
            if dob != reference_dob:
                flags.append({"type": "dob_mismatch", "doc_type": d["doc_type"],
                              "detail": f"DOB {dob.isoformat()} vs {reference_dob.isoformat()} ({source})"})
    return flags
