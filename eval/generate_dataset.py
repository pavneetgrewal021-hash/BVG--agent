"""
Builds the synthetic evaluation set: one combined PDF per fake candidate
(like a real candidate's email attachment) plus ground-truth labels.

    python eval/generate_dataset.py

Writes eval/data/{dev,test}/<candidate_id>.pdf and eval/data/labels.json.
Same SEED -> same text and labels every time, so results stay comparable.
"""
import copy
import io
import json
import os
import random
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import fitz
import numpy as np
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

os.environ.setdefault("BGV_DB_PATH", ":memory:")  # set before importing the pipeline, so data/bgv.db is never touched
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.templates import TEMPLATES, NOT_A_DOCUMENT
from services.pipeline import compute_status

SEED = 2026
SCAN_PROBABILITY = 0.4
REQUIRED_DOCS = ["aadhaar", "pan", "10th_certificate"]
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Each candidate: list of (template, options). Options:
#   month=i         which payslip month
#   other_person    document belongs to someone else  -> expect name_mismatch flag
#   dob_shift=days  DOB printed differently           -> expect dob_mismatch flag
#   initials        name printed as initials ("S. Verma"), a legitimate variant: no flag
SCENARIOS = {
    "dev": [
        [("aadhaar", {}), ("pan", {}), ("10th_certificate", {}), ("12th_certificate", {})],
        [("cover_letter", {}), ("pan", {}), ("10th_certificate", {}), ("marksheet", {}),
         ("degree_certificate", {"initials": True})],
        [("offer_letter", {}), ("payslip", {"month": 0}), ("experience_letter", {})],
        [("aadhaar", {}), ("pan", {"dob_shift": 400}), ("10th_certificate", {}),
         ("payslip", {"month": 0}), ("payslip", {"month": 1}), ("bank_statement", {})],
        [("passport", {}), ("pan", {}), ("12th_certificate", {}), ("provisional_certificate", {}),
         ("bgv_consent", {})],
    ],
    "test": [
        [("aadhaar", {}), ("pan", {}), ("10th_certificate", {}), ("degree_certificate", {})],
        [("cover_letter", {}), ("aadhaar", {}), ("10th_certificate", {"dob_shift": -730}),
         ("marksheet", {}), ("marksheet", {})],
        [("offer_letter", {}), ("relieving_letter", {}), ("form_16", {}), ("payslip", {"month": 0})],
        [("pan", {}), ("10th_certificate", {}), ("12th_certificate", {}),
         ("degree_certificate", {"initials": True}), ("provisional_certificate", {})],
        [("aadhaar", {}), ("pan", {}), ("10th_certificate", {}), ("driving_license", {}),
         ("bank_statement", {})],
        [("voter_id", {}), ("pan", {}), ("marksheet", {}), ("experience_letter", {}),
         ("court_record", {})],
        [("aadhaar", {}), ("pan", {}), ("bgv_consent", {}), ("10th_certificate", {}),
         ("police_verification", {})],
        [("passport", {}), ("aadhaar", {"other_person": True}), ("12th_certificate", {}),
         ("degree_certificate", {}), ("offer_letter", {})],
        [("aadhaar", {}), ("blank_page", {}), ("pan", {}), ("10th_certificate", {})],
        [("12th_certificate", {}), ("degree_certificate", {}), ("marksheet", {}),
         ("payslip", {"month": 0}), ("payslip", {"month": 1})],
    ],
}

FIRST_M = ["Aarav", "Rohan", "Kabir", "Arjun", "Nikhil", "Harpreet", "Farhan", "Joseph", "Vivek", "Siddharth"]
FIRST_F = ["Ananya", "Diya", "Ishita", "Kavya", "Meera", "Simran", "Zoya", "Gurleen", "Neha", "Tanvi"]
LAST = ["Sharma", "Verma", "Gupta", "Gill", "Iyer", "Nair", "Reddy", "Das", "Khan", "Fernandes",
        "Joshi", "Mehta", "Patel", "Malhotra", "Menon", "Sandhu"]
FATHER_FIRST = ["Rajesh", "Sunil", "Anil", "Manoj", "Gurpreet", "Imran", "Thomas", "Prakash"]
MOTHER_FIRST = ["Sunita", "Rekha", "Kiran", "Anjali", "Parveen", "Mary", "Lata", "Jaspreet"]
PLACES = [  # city, state, state board, pin prefix
    ("Chandigarh", "Chandigarh", "Punjab School Education Board", "1600"),
    ("Ludhiana", "Punjab", "Punjab School Education Board", "1410"),
    ("Pune", "Maharashtra", "Maharashtra State Board of Secondary and Higher Secondary Education", "4110"),
    ("Jaipur", "Rajasthan", "Board of Secondary Education, Rajasthan", "3020"),
    ("Kochi", "Kerala", "Kerala Board of Public Examinations", "6820"),
]
UNIVERSITIES = [("Riverside Technical University", "rtu.example.edu"),
                ("Northern Plains University", "npu.example.edu"),
                ("Western Ghats University", "wgu.example.edu")]
COLLEGES = ["Sunrise Institute of Engineering", "Lakeview College of Technology"]
COMPANIES = ["Northwind Analytics Pvt. Ltd.", "Bluepeak Software Solutions", "Orbitra Technologies"]
PREV_COMPANIES = ["Lumen Retail Tech Pvt. Ltd.", "Saffron Fintech Services", "Greyline Consulting LLP"]
BANKS = [("Unity Federal Bank", "UFBK"), ("Coastal Commercial Bank", "CCBL")]

# Verhoeff checksum tables (the check digit scheme Aadhaar numbers use)
V_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
V_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
V_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_check_digit(number):
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = V_D[c][V_P[(i + 1) % 8][int(digit)]]
    return str(V_INV[c])


def verhoeff_valid(number):
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = V_D[c][V_P[i % 8][int(digit)]]
    return c == 0


def digits(rng, n):
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def letters(rng, n):
    return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(n))


def rand_date(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


def make_person(rng, idx):
    gender = rng.choice(["Male", "Female"])
    first = rng.choice(FIRST_M if gender == "Male" else FIRST_F)
    last = rng.choice(LAST)
    city, state, board, pin = rng.choice(PLACES)
    university, uni_domain = rng.choice(UNIVERSITIES)
    bank, ifsc_prefix = rng.choice(BANKS)
    dob = rand_date(rng, date(1995, 1, 1), date(2000, 12, 31))
    grad_year = dob.year + 22
    prev_join = date(grad_year, 7, 1) + timedelta(days=rng.randint(0, 60))
    exit_date = prev_join + timedelta(days=rng.randint(400, 1000))
    offer_date = exit_date + timedelta(days=rng.randint(10, 40))
    aadhaar_base = str(rng.randint(2, 9)) + digits(rng, 10)
    aadhaar = aadhaar_base + verhoeff_check_digit(aadhaar_base)
    assert verhoeff_valid(aadhaar)
    basic = rng.randrange(25000, 60000, 500)
    hra, special = basic // 2, basic // 4
    pf, tds = basic * 12 // 100, rng.randrange(1000, 6000, 100)
    gross = basic + hra + special
    deductions = pf + 200 + tds
    phone = "9" + digits(rng, 9)

    p = SimpleNamespace(
        idx=idx, first=first, last=last, name=f"{first} {last}", gender=gender, dob=dob,
        relation="S/O" if gender == "Male" else "D/O",
        father=f"{rng.choice(FATHER_FIRST)} {last}", mother=f"{rng.choice(MOTHER_FIRST)} {last}",
        city=city, state=state, state_board=board,
        address=f"House No. {rng.randint(1, 999)}, Sector {rng.randint(1, 60)}, {city} - {pin}{rng.randint(10, 99)}",
        phone=phone, phone_masked="XXXXXX" + phone[-4:],
        email=f"{first.lower()}.{last.lower()}{idx}@example.com",
        aadhaar=aadhaar, aadhaar_fmt=f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}",
        enrolment_no=f"{digits(rng, 4)}/{digits(rng, 5)}/{digits(rng, 5)}", vid=digits(rng, 16),
        aadhaar_issue=rand_date(rng, date(2018, 1, 1), date(2025, 6, 30)),
        # PAN: 3 letters + P (individual) + first letter of surname + 4 digits + letter
        pan=letters(rng, 3) + "P" + last[0].upper() + digits(rng, 4) + letters(rng, 1),
        pan_issue=rand_date(rng, date(dob.year + 18, 1, 1), date(dob.year + 21, 12, 31)),
        passport_no=letters(rng, 1) + digits(rng, 7), passport_office=city,
        passport_issue=rand_date(rng, date(2017, 1, 1), date(2023, 12, 31)),
        passport_file=letters(rng, 2) + digits(rng, 10),
        dl_no=f"{state[:2].upper()}{rng.randint(1, 30):02d} {dob.year + 19}{digits(rng, 7)}",
        dl_issue=date(dob.year + 19, rng.randint(1, 12), rng.randint(1, 28)),
        blood_group=rng.choice(["A+", "B+", "O+", "AB+", "O-"]),
        epic=letters(rng, 3) + digits(rng, 7), epic_year=2024,
        school=f"{rng.choice(['St. Mary', 'Delhi Public', 'Kendriya Vidyalaya', 'Little Flower'])} School, {city}",
        roll_10=digits(rng, 7), reg_10=digits(rng, 10), roll_12=digits(rng, 7),
        tenth_issue=date(dob.year + 16, 5, rng.randint(10, 28)),
        twelfth_issue=date(dob.year + 18, 5, rng.randint(10, 28)),
        university=university, uni_domain=uni_domain, college=rng.choice(COLLEGES),
        degree_long="Bachelor of Technology (Computer Science and Engineering)", degree_short="B.Tech",
        semester=rng.choice(["III", "IV", "V", "VI", "VII"]), session=f"{grad_year - 2}-{str(grad_year - 1)[2:]}",
        uni_roll=f"{grad_year - 4}{letters(rng, 2)}{digits(rng, 4)}", grad_year=grad_year,
        degree_serial=digits(rng, 8),
        degree_issue=date(grad_year + 1, rng.randint(1, 4), rng.randint(1, 28)),
        provisional_issue=date(grad_year, 7, rng.randint(1, 28)),
        company=rng.choice(COMPANIES), role="Software Engineer", ctc=f"{rng.randint(6, 18)},00,000",
        offer_date=offer_date, joining_date=offer_date + timedelta(days=30),
        prev_company=rng.choice(PREV_COMPANIES), prev_role="Associate Software Engineer",
        emp_id=f"E{digits(rng, 5)}", prev_join=prev_join, exit_date=exit_date,
        resign_date=exit_date - timedelta(days=60),
        payslip_months=[exit_date.replace(day=1) - timedelta(days=1),
                        (exit_date.replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=1)],
        bank=bank, ifsc=f"{ifsc_prefix}0{digits(rng, 6)}", account_masked="XXXXXXXX" + digits(rng, 4),
        basic=basic, hra=hra, special=special, pf=pf, tds=tds, gross=gross,
        deductions=deductions, net=gross - deductions,
        stmt_from=exit_date.replace(day=1) - timedelta(days=30), stmt_to=exit_date.replace(day=1) - timedelta(days=1),
        opening=rng.randint(20000, 200000),
        consent_date=offer_date + timedelta(days=5),
        pv_no=digits(rng, 6), pv_date=offer_date + timedelta(days=15),
        court_date=offer_date + timedelta(days=12),
    )
    p.passport_expiry = p.passport_issue + timedelta(days=3652) - timedelta(days=1)
    p.dl_expiry = date(dob.year + 40, p.dl_issue.month, p.dl_issue.day)
    p.doc_name, p.doc_dob = p.name, p.dob
    return p


def render_digital(pages):
    """Text pages -> PDF bytes with a real text layer."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    for lines in pages:
        c.saveState()  # diagonal watermark
        c.setFillGray(0.88)
        c.setFont("Helvetica-Bold", 70)
        c.translate(width / 2, height / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, "SPECIMEN")
        c.restoreState()

        y = height - 60
        for line in lines:
            if line.startswith("# "):
                c.setFont("Helvetica-Bold", 14)
                c.drawString(50, y, line[2:])
                y -= 24
            else:
                c.setFont("Helvetica", 10)
                c.drawString(50, y, line)
                y -= 16
        c.setFont("Helvetica", 7)
        c.drawString(50, 30, "SPECIMEN - SYNTHETIC TEST DATA - NOT A REAL DOCUMENT")
        c.showPage()
    c.save()
    return buf.getvalue()


def scan(pdf_bytes, rng):
    """Turns a digital PDF into an image-only 'scan': no text layer, slight tilt, blur, noise."""
    src = fitz.open("pdf", pdf_bytes)
    out = fitz.open()
    angle = rng.uniform(-1.5, 1.5)
    noise_rng = np.random.default_rng(rng.randint(0, 2**32 - 1))
    for page in src:
        pix = page.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        img = img.rotate(angle, fillcolor=255, resample=Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        arr = np.asarray(img, dtype=np.float32) + noise_rng.normal(0, 14, (img.height, img.width))
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        jpg = io.BytesIO()
        img.save(jpg, format="JPEG", quality=70)
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=jpg.getvalue())
    src.close()
    return out.tobytes()


def build_document(person, template, opts, variant, other):
    p = copy.copy(person)
    if opts.get("other_person"):
        p.doc_name, p.doc_dob = other.name, other.dob
    if opts.get("dob_shift"):
        p.doc_dob = person.dob + timedelta(days=opts["dob_shift"])
    if opts.get("initials"):
        p.doc_name = f"{person.first[0]}. {person.last}"

    fn, _ = TEMPLATES[template]
    if template == "payslip":
        pages, truth = fn(p, variant, month=person.payslip_months[opts.get("month", 0)])
    else:
        pages, truth = fn(p, variant)
    return pages, truth


def main():
    rng = random.Random(SEED)
    labels = {"seed": SEED, "required_docs": REQUIRED_DOCS, "candidates": []}
    idx = 0

    for split, scenarios in SCENARIOS.items():
        os.makedirs(os.path.join(OUT_DIR, split), exist_ok=True)
        for docs in scenarios:
            idx += 1
            person = make_person(rng, idx)
            other = make_person(rng, 900 + idx)  # someone else, for planted mismatches
            cid = f"{split.upper()}{idx:02d}"
            combined = fitz.open()
            documents, flags = [], []

            for n, (template, opts) in enumerate(docs):
                _, n_variants = TEMPLATES[template]
                variant = 0 if split == "dev" else rng.randint(1, n_variants - 1)
                pages, truth = build_document(person, template, opts, variant, other)
                scanned = rng.random() < SCAN_PROBABILITY
                pdf_bytes = render_digital(pages)
                if scanned:
                    pdf_bytes = scan(pdf_bytes, rng)

                start = len(combined)
                with fitz.open("pdf", pdf_bytes) as doc_pdf:
                    combined.insert_pdf(doc_pdf)
                doc_type = "unknown" if template in NOT_A_DOCUMENT else template

                if opts.get("other_person"):
                    flags.append({"type": "name_mismatch", "doc_type": doc_type})
                if opts.get("dob_shift"):
                    flags.append({"type": "dob_mismatch", "doc_type": doc_type})

                documents.append({
                    "doc_id": f"{cid}-{n + 1}", "doc_type": doc_type, "template": template,
                    "variant": variant, "scanned": scanned,
                    "pages": list(range(start, len(combined))),
                    "name_variant": "initials" if opts.get("initials") else None,
                    "fields": truth,
                })

            pdf_rel = f"{split}/{cid}.pdf"
            combined.save(os.path.join(OUT_DIR, pdf_rel))
            n_pages = len(combined)
            combined.close()

            present = {d["doc_type"] for d in documents if d["doc_type"] != "unknown"}
            status, _, _ = compute_status(REQUIRED_DOCS, present)
            labels["candidates"].append({
                "candidate_id": cid, "split": split, "pdf": pdf_rel, "pages": n_pages,
                "name": person.name, "dob": person.dob.isoformat(), "email": person.email,
                "true_status": status, "expected_flags": flags, "documents": documents,
            })
            print(f"{cid}: {n_pages} pages, {len(documents)} docs, "
                  f"{sum(d['scanned'] for d in documents)} scanned, status {status}")

    with open(os.path.join(OUT_DIR, "labels.json"), "w") as f:
        json.dump(labels, f, indent=2)
    print(f"\nWrote {len(labels['candidates'])} candidates to {OUT_DIR}")


if __name__ == "__main__":
    main()
