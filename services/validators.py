"""
Deterministic checks for extracted fields. No model involved: these rules are
exact, explainable and free, which is why they are code and not prompts.
"""
import re
from datetime import date, datetime

# Verhoeff checksum tables: the last digit of every Aadhaar number is a Verhoeff check digit
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]

# Exact formats of Indian ID numbers, written without spaces or hyphens
ID_FORMATS = {
    "aadhaar": re.compile(r"[2-9]\d{11}"),
    # 3 letters, holder type (P = individual), first letter of surname, 4 digits, check letter
    "pan": re.compile(r"[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]"),
    "passport": re.compile(r"[A-Z]\d{7}"),
    # state code, RTO code, year of issue, 7-digit serial
    "driving_license": re.compile(r"[A-Z]{2}\d{2}(19|20)\d{2}\d{7}"),
    "voter_id": re.compile(r"[A-Z]{3}\d{7}"),
}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y"]


def verhoeff_valid(number):
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(digit)]]
    return c == 0


def compact(value):
    """ID number without spaces, hyphens or slashes, upper case."""
    return re.sub(r"[\s\-/]", "", value or "").upper()


def normalise_text(text):
    return " ".join((text or "").lower().split())


def normalise_name(name):
    """'S. VERMA ' -> 's verma': case, punctuation and spacing do not count as differences."""
    return " ".join(re.sub(r"[^a-z\s]", " ", (name or "").lower()).split())


def parse_date(value):
    """Accepts the common Indian date formats; returns a date or None."""
    if not value:
        return None
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def date_on_page(d, text):
    """Is this date printed on the page in any usual format? (catches day/month swaps)"""
    candidates = [d.strftime("%d/%m/%Y"), d.strftime("%d-%m-%Y"), d.strftime("%d.%m.%Y"),
                  d.strftime("%d %B %Y"), d.strftime("%d %b %Y"), d.isoformat()]
    page = normalise_text(text)
    return any(normalise_text(c) in page for c in candidates)


def name_on_page(name, text):
    """Every word of the name appears on the page (order-free: passports split surname and given names)."""
    words = normalise_name(name).split()
    page_words = set(normalise_name(text).split())
    return bool(words) and all(w in page_words for w in words)


def number_on_page(number, text):
    return bool(number) and compact(number) in compact(text)


def check_id_number(doc_type, number, holder_name=None):
    """List of problems with an ID number (empty list = valid)."""
    fmt = ID_FORMATS.get(doc_type)
    if fmt is None or not number:
        return []
    n = compact(number)
    if not fmt.fullmatch(n):
        return [f"not a valid {doc_type} number format"]
    problems = []
    if doc_type == "aadhaar" and not verhoeff_valid(n):
        problems.append("Aadhaar check digit is wrong (mistyped, misread or altered number)")
    if doc_type == "pan":
        if n[3] != "P":
            problems.append(f"PAN holder type is '{n[3]}', not 'P' (individual)")
        # The surname may be printed first or last ("Sharma Arjun"), so accept either end
        words = normalise_name(holder_name).split() if holder_name else []
        if words and n[4] not in {words[0][0].upper(), words[-1][0].upper()}:
            problems.append(f"PAN 5th letter '{n[4]}' does not match the surname initial "
                            f"('{words[-1][0].upper()}' or '{words[0][0].upper()}')")
    return problems


def check_dob(d, today=None):
    today = today or date.today()
    age = (today - d).days / 365.25
    if age < 15 or age > 80:
        return [f"implausible date of birth (age {age:.0f})"]
    return []


def find_id_numbers(doc_type, text):
    """Every substring of the page that matches the ID format (used to cross-check the LLM)."""
    fmt = ID_FORMATS.get(doc_type)
    if fmt is None:
        return []
    # Join digit groups like '1234 5678 9012' or 'PB01 2014...' before matching
    joined = re.sub(r"(?<=[A-Z0-9])[ \-](?=[A-Z0-9])", "", text.upper())
    found = []
    # Boundaries stop a 12-digit Aadhaar "match" inside a longer number such as a 16-digit VID
    for m in re.finditer(r"(?<![A-Z0-9])" + fmt.pattern + r"(?![A-Z0-9])", joined):
        candidate = m.group(0)
        if candidate not in found:
            found.append(candidate)
    return found


def mask_aadhaar(number):
    """UIDAI guidance: never display or store the full Aadhaar number."""
    n = compact(number)
    return f"XXXX XXXX {n[-4:]}" if len(n) == 12 else number
