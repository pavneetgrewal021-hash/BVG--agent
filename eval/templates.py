"""
Text templates for SYNTHETIC test documents. Every value is invented.

Each template is  fn(p, v) -> (pages, fields)
  p      : a fake person (see generate_dataset.make_person)
  v      : wording variant. The dev split uses variant 0 only; the test split
           uses variants 1+ so test numbers measure unseen wording.
  pages  : list of pages, each a list of text lines ("# " prefix = heading)
  fields : ground truth for later field-extraction evals
           {name, dob, doc_number, issue_date}, dates as YYYY-MM-DD or None

Wording follows the layout of the real Indian documents (that is what the
classifier will see in production). Institutions that are not government
issuers (schools, universities, companies, banks) are fictional.
"""

def dmy(d):
    return d.strftime("%d/%m/%Y")

def long_date(d):
    return d.strftime("%d %B %Y")

def iso(d):
    return d.isoformat() if d else None

def fields(name, dob=None, doc_number=None, issue_date=None):
    return {"name": name, "dob": iso(dob), "doc_number": doc_number, "issue_date": iso(issue_date)}


# ---------------------------------------------------------------- identity

def aadhaar(p, v):
    name = p.doc_name
    if v == 0:  # card: front + back
        front = [
            "# Government of India",
            "Unique Identification Authority of India",
            "",
            name,
            f"DOB: {dmy(p.doc_dob)}",
            p.gender.upper(),
            "",
            p.aadhaar_fmt,
            "Mera Aadhaar, Meri Pehchaan",
        ]
        back = [
            "# Unique Identification Authority of India",
            "Address:",
            f"{p.relation} {p.father},",
            p.address,
            "",
            p.aadhaar_fmt,
            "1947   help@uidai.gov.in   www.uidai.gov.in",
        ]
        return [front, back], fields(name, p.doc_dob, p.aadhaar)
    # e-Aadhaar letter
    page = [
        "# Unique Identification Authority of India",
        "Government of India",
        f"Enrolment No.: {p.enrolment_no}",
        "",
        "To",
        name,
        f"{p.relation} {p.father}",
        p.address,
        f"Mobile: {p.phone_masked}",
        "",
        f"Your Aadhaar No. : {p.aadhaar_fmt}",
        f"VID : {p.vid}",
        f"Date of Birth: {dmy(p.doc_dob)}    Gender: {p.gender}",
        "",
        "Aadhaar is a proof of identity, not of citizenship.",
        f"Download Date: {dmy(p.aadhaar_issue)}",
    ]
    return [page], fields(name, p.doc_dob, p.aadhaar, p.aadhaar_issue)


def pan(p, v):
    name = p.doc_name.upper()
    if v == 0:
        page = [
            "# INCOME TAX DEPARTMENT",
            "GOVT. OF INDIA",
            "Permanent Account Number Card",
            p.pan,
            "Name",
            name,
            "Father's Name",
            p.father.upper(),
            "Date of Birth",
            dmy(p.doc_dob),
            "Signature",
        ]
        return [page], fields(p.doc_name, p.doc_dob, p.pan)
    page = [
        "# e-Permanent Account Number (e-PAN) Card",
        "Income Tax Department, Government of India",
        "",
        f"PAN: {p.pan}",
        f"Name: {name}",
        f"Father's Name: {p.father.upper()}",
        f"Date of Birth: {dmy(p.doc_dob)}",
        f"Date of Allotment: {dmy(p.pan_issue)}",
        "",
        "This is a digitally signed e-PAN card and is valid as proof of PAN.",
    ]
    return [page], fields(p.doc_name, p.doc_dob, p.pan, p.pan_issue)


def passport(p, v):
    surname, given = p.last.upper(), p.doc_name.rsplit(" ", 1)[0].upper()
    data = [
        "# REPUBLIC OF INDIA",
        "PASSPORT",
        f"Type: P    Country Code: IND    Passport No.: {p.passport_no}",
        f"Surname: {surname}",
        f"Given Name(s): {given}",
        f"Nationality: INDIAN    Sex: {p.gender[0]}    Date of Birth: {dmy(p.doc_dob)}",
        f"Place of Birth: {p.city.upper()}",
        f"Place of Issue: {p.passport_office.upper()}",
        f"Date of Issue: {dmy(p.passport_issue)}    Date of Expiry: {dmy(p.passport_expiry)}",
        "",
        f"P<IND{surname}<<{given.replace(' ', '<')}<<<<<<<<<<<<<<<<",
        f"{p.passport_no}<4IND{p.doc_dob.strftime('%y%m%d')}<<<<<<<<<<<<<<",
    ]
    f = fields(p.doc_name, p.doc_dob, p.passport_no, p.passport_issue)
    if v == 0:
        last = [
            f"Name of Father / Legal Guardian: {p.father.upper()}",
            f"Name of Mother: {p.mother.upper()}",
            "Name of Spouse:",
            f"Address: {p.address.upper()}",
            "Old Passport No. with Date and Place of Issue:",
            f"File No.: {p.passport_file}",
        ]
        return [data, last], f
    return [data], f


def driving_license(p, v):
    if v == 0:
        page = [
            "# Union of India",
            "Driving Licence",
            f"Issued by: Transport Department, Government of {p.state}",
            f"Licence No.: {p.dl_no}",
            f"Name: {p.doc_name}",
            f"S/D/W of: {p.father}",
            f"Date of Birth: {dmy(p.doc_dob)}    Blood Group: {p.blood_group}",
            f"Address: {p.address}",
            f"Date of Issue: {dmy(p.dl_issue)}    Valid Till (NT): {dmy(p.dl_expiry)}",
            "Class of Vehicle: LMV, MCWG",
        ]
    else:
        page = [
            "# FORM 7",
            "[See Rule 16(2)]",
            "Licence to drive motor vehicles",
            f"DL No: {p.dl_no}",
            f"Name: {p.doc_name}",
            f"Son/Daughter/Wife of: {p.father}",
            f"DOB: {dmy(p.doc_dob)}",
            f"Issue Date: {dmy(p.dl_issue)}",
            "Authorisation to drive: Motor Cycle with Gear, Light Motor Vehicle",
            "Licensing Authority",
        ]
    return [page], fields(p.doc_name, p.doc_dob, p.dl_no, p.dl_issue)


def voter_id(p, v):
    if v == 0:
        page = [
            "# ELECTION COMMISSION OF INDIA",
            "ELECTOR PHOTO IDENTITY CARD",
            f"EPIC No.: {p.epic}",
            f"Elector's Name: {p.doc_name}",
            f"Father's Name: {p.father}",
            f"Sex: {p.gender}",
            f"Date of Birth: {dmy(p.doc_dob)}",
        ]
    else:
        page = [
            "# e-EPIC",
            "Election Commission of India",
            f"EPIC Number: {p.epic}",
            f"Name: {p.doc_name}",
            f"Relation's Name: {p.father}",
            f"Gender: {p.gender}    Age as on 01.01.{p.epic_year}: {p.epic_year - p.dob.year}",
            f"Address: {p.address}",
            f"Electoral Registration Officer, {p.city} Assembly Constituency",
        ]
    return [page], fields(p.doc_name, p.doc_dob if v == 0 else None, p.epic)


# --------------------------------------------------------------- education

def tenth(p, v):
    year = p.dob.year + 16
    issue = p.tenth_issue
    if v == 0:
        lines = [
            "# Central Board of Secondary Education",
            f"Secondary School Examination, {year}",
            "Marks Statement cum Certificate",
            f"This is to certify that {p.doc_name.upper()}",
            f"Mother's Name: {p.mother.upper()}    Father's Name: {p.father.upper()}",
            f"Date of Birth: {dmy(p.doc_dob)}",
            f"School: {p.school}",
            f"Roll No.: {p.roll_10}",
            "has passed the examination with the following marks:",
            "English Language & Literature   086   A2",
            "Hindi Course-A                   079   B1",
            "Mathematics Standard             092   A1",
            "Science                          088   A2",
            "Social Science                   084   A2",
            "Result: PASS",
            f"Dated: {dmy(issue)}",
        ]
    elif v == 1:
        lines = [
            f"# {p.state_board}",
            f"Matriculation Examination {year}",
            "Certificate cum Detailed Marks Card",
            f"Name: {p.doc_name}",
            f"Father's Name: {p.father}",
            f"Date of Birth: {dmy(p.doc_dob)}",
            f"Roll No.: {p.roll_10}    Registration No.: {p.reg_10}",
            "Punjabi 84/100   English 81/100   Mathematics 93/100   Science 88/100   Social Studies 79/100",
            "Total: 425/500    Result: Pass (First Division)",
            f"Date of Issue: {dmy(issue)}",
            "Controller of Examinations",
        ]
    else:
        lines = [
            "# Council for the Indian School Certificate Examinations",
            f"Indian Certificate of Secondary Education Examination {year}",
            "Pass Certificate",
            f"{p.doc_name}",
            f"Unique ID: {p.roll_10}    School: {p.school}",
            f"Date of Birth: {dmy(p.doc_dob)}",
            "Subjects: English, Second Language, History Civics & Geography, Mathematics, Science, Computer Applications",
            f"New Delhi, {long_date(issue)}",
            "Chief Executive & Secretary",
        ]
    return [lines], fields(p.doc_name, p.doc_dob, p.roll_10, issue)


def twelfth(p, v):
    year = p.dob.year + 18
    issue = p.twelfth_issue
    if v == 0:
        lines = [
            "# Central Board of Secondary Education",
            f"Senior School Certificate Examination, {year}",
            "Marks Statement cum Certificate",
            f"This is to certify that {p.doc_name.upper()}",
            f"Mother's Name: {p.mother.upper()}    Father's Name: {p.father.upper()}",
            f"School: {p.school}",
            f"Roll No.: {p.roll_12}",
            "English Core 082 A2 | Physics 078 B1 | Chemistry 081 A2 | Mathematics 090 A1 | Computer Science 094 A1",
            "Result: PASS",
            f"Dated: {dmy(issue)}",
        ]
    elif v == 1:
        lines = [
            f"# {p.state_board}",
            f"Senior Secondary Certificate Examination (Class XII) {year}",
            "Detailed Marks Card",
            f"Name: {p.doc_name}    Father's Name: {p.father}",
            f"Roll No.: {p.roll_12}",
            "Stream: Non-Medical",
            "General English 78   Punjabi 85   Physics 81   Chemistry 76   Mathematics 89",
            "Total: 409/500    Result: Pass",
            f"Date of Issue: {dmy(issue)}",
        ]
    else:
        lines = [
            "# Council for the Indian School Certificate Examinations",
            f"Indian School Certificate Examination {year}",
            "Year 12 Pass Certificate",
            f"{p.doc_name}",
            f"Unique ID: {p.roll_12}    School: {p.school}",
            "Subjects: English, Physics, Chemistry, Mathematics, Computer Science",
            f"New Delhi, {long_date(issue)}",
        ]
    return [lines], fields(p.doc_name, None, p.roll_12, issue)


def marksheet(p, v):
    sem = p.semester
    if v == 0:
        lines = [
            f"# {p.university}",
            "Grade Card",
            f"Programme: {p.degree_long}",
            f"Semester: {sem}    Session: {p.session}",
            f"Name: {p.doc_name}    Roll No.: {p.uni_roll}",
            "Course Code   Course Title                         Credits   Grade",
            "CS301         Data Structures                      4         A",
            "CS303         Database Management Systems          4         A+",
            "CS305         Computer Networks                    3         B+",
            "MA301         Discrete Mathematics                 3         A",
            "SGPA: 8.6    CGPA: 8.2",
            "Controller of Examinations",
        ]
    else:
        lines = [
            "# Statement of Marks",
            f"{p.college}",
            f"(Affiliated to {p.university})",
            f"Examination: {p.degree_short} Semester {sem}, {p.session}",
            f"Name of Candidate: {p.doc_name}",
            f"Registration No.: {p.uni_roll}",
            "Paper                          Max   Obtained",
            "Operating Systems              100   78",
            "Software Engineering           100   84",
            "Theory of Computation          100   71",
            "Grand Total: 233/300    Result: Pass",
        ]
    return [lines], fields(p.doc_name, None, p.uni_roll, None)


def degree(p, v):
    issue = p.degree_issue
    if v == 0:
        front = [
            f"# {p.university}",
            "This is to certify that",
            p.doc_name.upper(),
            f"having passed the examination held in {p.grad_year}",
            f"has been admitted to the degree of {p.degree_long}",
            "with First Division.",
            "Given under the seal of the University.",
            f"Convocation held on {long_date(issue)}",
            "Vice-Chancellor",
        ]
        back = [
            f"Serial No.: {p.degree_serial}",
            f"Enrolment No.: {p.uni_roll}",
            f"This certificate can be verified at verify.{p.uni_domain}",
        ]
        return [front, back], fields(p.doc_name, None, p.degree_serial, issue)
    page = [
        f"# The Senate of {p.university}",
        f"hereby confers the degree of {p.degree_long}",
        f"upon {p.doc_name}",
        f"who has fulfilled all the requirements for the said degree in {p.grad_year}.",
        f"Date: {dmy(issue)}",
        f"Certificate No.: {p.degree_serial}",
        "Registrar",
    ]
    return [page], fields(p.doc_name, None, p.degree_serial, issue)


def provisional(p, v):
    issue = p.provisional_issue
    if v == 0:
        lines = [
            f"# {p.university}",
            "Provisional Certificate",
            f"This is to certify that {p.doc_name}, Roll No. {p.uni_roll},",
            f"has passed the {p.degree_short} examination held in {p.grad_year}",
            "and is provisionally eligible for the award of the degree.",
            "This certificate is valid until the original degree is issued.",
            f"Date: {dmy(issue)}",
            "Controller of Examinations",
        ]
    else:
        lines = [
            "# Provisional Degree Certificate",
            f"{p.college}",
            f"Certified that {p.doc_name} has successfully completed the {p.degree_long} programme",
            f"in {p.grad_year} and has been provisionally passed, pending the formal award of degree.",
            f"Ref. No.: PDC/{p.grad_year}/{p.uni_roll}",
            f"Issued on: {dmy(issue)}",
        ]
    return [lines], fields(p.doc_name, None, p.uni_roll, issue)


# -------------------------------------------------------------- employment

def offer_letter(p, v):
    issue = p.offer_date
    if v == 0:
        lines = [
            f"# {p.company}",
            f"Date: {dmy(issue)}",
            f"Dear {p.doc_name},",
            "Offer of Employment",
            f"We are pleased to offer you the position of {p.role} at our {p.city} office.",
            f"Your annual CTC will be INR {p.ctc} and your joining date will be {dmy(p.joining_date)}.",
            "On the day of joining, please carry originals and self-attested copies of:",
            "- Aadhaar card and PAN card",
            "- 10th and 12th mark sheets, degree certificate",
            "- Relieving letter from your previous employer (if applicable)",
            "We look forward to welcoming you.",
            "Head - Talent Acquisition",
        ]
    else:
        lines = [
            f"# {p.company}",
            "Letter of Offer",
            f"{dmy(issue)}",
            f"Dear {p.doc_name},",
            f"Further to your interview, we are delighted to offer you the role of {p.role}.",
            f"Proposed date of joining: {dmy(p.joining_date)}. Location: {p.city}.",
            "Documents required at joining: government photo ID (Aadhaar or Passport), PAN,",
            "educational certificates and two passport-size photographs.",
            "Kindly sign and return a copy of this letter as your acceptance.",
            "HR Manager",
        ]
    return [lines], fields(p.doc_name, None, None, issue)


def experience_letter(p, v):
    issue = p.exit_date
    if v == 0:
        lines = [
            f"# {p.prev_company}",
            "TO WHOMSOEVER IT MAY CONCERN",
            f"This is to certify that {p.doc_name} (Employee ID {p.emp_id}) was employed with",
            f"{p.prev_company} as {p.prev_role} from {long_date(p.prev_join)} to {long_date(p.exit_date)}.",
            "During the tenure, we found the employee sincere and hardworking.",
            "We wish them all the best for future endeavours.",
            "Manager - Human Resources",
        ]
    else:
        lines = [
            f"# {p.prev_company}",
            "Experience Certificate",
            f"Date: {dmy(issue)}",
            f"We certify that {p.doc_name} worked with us as {p.prev_role}",
            f"between {dmy(p.prev_join)} and {dmy(p.exit_date)}.",
            "Their conduct during this period was good.",
            "Authorised Signatory",
        ]
    # wording 0 prints no letter date, so there is no issue date to extract
    return [lines], fields(p.doc_name, None, p.emp_id, issue if v != 0 else None)


def relieving_letter(p, v):
    issue = p.exit_date
    if v == 0:
        lines = [
            f"# {p.prev_company}",
            "Relieving Letter",
            f"Date: {dmy(issue)}",
            f"Dear {p.doc_name},",
            f"This is with reference to your resignation dated {dmy(p.resign_date)}.",
            f"You are relieved from the services of the company at the close of business on {dmy(p.exit_date)}.",
            "Your full and final settlement will be processed as per company policy.",
            "Human Resources",
        ]
    else:
        lines = [
            f"# {p.prev_company}",
            f"Ref: HR/REL/{p.emp_id}",
            f"{dmy(issue)}",
            f"Dear {p.doc_name},",
            f"We accept your resignation. Your last working day with us was {dmy(p.exit_date)},",
            "and you have completed all exit formalities.",
            "Thank you for your contributions.",
            "HR Business Partner",
        ]
    return [lines], fields(p.doc_name, None, p.emp_id, issue)


def payslip(p, v, month=None):
    month = month or p.payslip_months[0]
    title = "Payslip" if v == 0 else "Salary Slip"
    lines = [
        f"# {p.prev_company}",
        f"{title} for the month of {month.strftime('%B %Y')}",
        f"Employee Name: {p.doc_name}    Employee ID: {p.emp_id}",
        f"Designation: {p.prev_role}    PAN: {p.pan}",
        f"Bank: {p.bank}    A/c No.: {p.account_masked}",
        "Earnings                       Deductions",
        f"Basic Salary   {p.basic:>8}       Provident Fund   {p.pf:>6}",
        f"HRA            {p.hra:>8}       Professional Tax    200",
        f"Special Allow. {p.special:>8}       Income Tax (TDS) {p.tds:>6}",
        f"Gross Salary   {p.gross:>8}       Total Deductions {p.deductions:>6}",
        f"Net Pay: INR {p.net}",
    ]
    return [lines], fields(p.doc_name, None, p.emp_id, None)


def form_16(p, v):
    ay = f"{p.exit_date.year}-{str(p.exit_date.year + 1)[2:]}"
    if v == 0:
        lines = [
            "# FORM NO. 16",
            "[See rule 31(1)(a)]",
            "PART A",
            "Certificate under section 203 of the Income-tax Act, 1961 for tax deducted at source on salary",
            f"Name and address of the Employer: {p.prev_company}, {p.city}",
            f"Name of the Employee: {p.doc_name.upper()}",
            f"PAN of the Employee: {p.pan}",
            f"Assessment Year: {ay}",
            f"Period with the Employer: {dmy(p.prev_join)} to {dmy(p.exit_date)}",
            f"Total tax deposited: {p.tds * 12}",
        ]
    else:
        lines = [
            "# Form 16 - Part B (Annexure)",
            "Details of Salary Paid and any other income and tax deducted",
            f"Employee: {p.doc_name}    PAN: {p.pan}",
            f"Assessment Year {ay}",
            f"1. Gross Salary: {p.gross * 12}",
            "2. Less: Allowances exempt under section 10",
            "3. Deductions under Chapter VI-A (80C, 80D)",
            f"4. Tax payable: {p.tds * 12}",
            "Verification: I, the authorised signatory, certify that the information given above is true.",
        ]
    return [lines], fields(p.doc_name, None, p.pan, None)


def bank_statement(p, v):
    title = "Account Statement" if v == 0 else "Statement of Account"
    lines = [
        f"# {p.bank}",
        title,
        f"Account Holder: {p.doc_name}",
        f"Account Number: {p.account_masked}    IFSC: {p.ifsc}",
        f"Statement Period: {dmy(p.stmt_from)} to {dmy(p.stmt_to)}",
        f"Opening Balance: {p.opening}",
        "Date         Narration                          Debit      Credit     Balance",
        f"{dmy(p.stmt_from)}   NEFT SALARY {p.prev_company[:18].upper():18}              {p.net:>8}   {p.opening + p.net}",
        f"{dmy(p.stmt_to)}   UPI/GROCERY STORE                  2,150                 {p.opening + p.net - 2150}",
        f"Closing Balance: {p.opening + p.net - 2150}",
    ]
    return [lines], fields(p.doc_name, None, p.account_masked, None)


# -------------------------------------------------------------- compliance

def bgv_consent(p, v):
    if v == 0:
        lines = [
            "# Background Verification Consent and Authorization Form",
            f"I, {p.doc_name}, hereby authorize {p.company} and its authorised agents",
            "to verify my educational, employment, address and criminal records.",
            f"Full Name: {p.doc_name}    Father's Name: {p.father}",
            f"Date of Birth: {dmy(p.doc_dob)}    Nationality: Indian",
            f"Aadhaar Number (last 4 digits): {p.aadhaar[-4:]}    PAN: {p.pan}",
            f"Current Address: {p.address}",
            f"Signature: ______________    Date: {dmy(p.consent_date)}",
        ]
    else:
        lines = [
            "# Authorization for Background Check",
            f"Candidate: {p.doc_name}",
            f"Place of Birth: {p.city}    Date of Birth: {dmy(p.doc_dob)}",
            f"I consent to {p.company} conducting background checks covering identity,",
            "education, previous employment and court records, now or during my employment.",
            f"Date: {dmy(p.consent_date)}",
        ]
    return [lines], fields(p.doc_name, p.doc_dob, None, p.consent_date)


def police_verification(p, v):
    if v == 0:
        lines = [
            f"# Office of the Superintendent of Police, District {p.city}",
            "Police Verification Certificate",
            f"No. PV/{p.pv_no}    Dated: {dmy(p.pv_date)}",
            f"This is to certify that {p.doc_name}, {p.relation} {p.father}, resident of {p.address},",
            "has been verified through local police station records.",
            "No criminal case is registered or pending against the applicant.",
            "Superintendent of Police",
        ]
    else:
        lines = [
            f"# {p.city} Police",
            "Character and Antecedents Verification Report",
            f"Applicant: {p.doc_name}    Father's Name: {p.father}",
            f"Address verified: {p.address}",
            "Antecedents: Nothing adverse found in police records.",
            f"Report No. {p.pv_no}, issued {dmy(p.pv_date)}",
            "Station House Officer",
        ]
    return [lines], fields(p.doc_name, None, p.pv_no, p.pv_date)


def court_record(p, v):
    if v == 0:
        lines = [
            "# Court Record Verification Report",
            f"Prepared for: {p.company}",
            f"Candidate: {p.doc_name}    Father's Name: {p.father}",
            f"Date of Birth: {dmy(p.doc_dob)}",
            f"Address searched: {p.address}",
            "Courts covered: Civil and Criminal courts - District Court, Sessions Court, High Court",
            "Period covered: last 7 years",
            "Result: No criminal record found against the candidate.",
            f"Verified on: {dmy(p.court_date)}",
        ]
    else:
        lines = [
            "# Litigation Database Search",
            f"Subject: {p.doc_name}, {p.relation} {p.father}",
            f"Jurisdiction: {p.state}",
            "Databases searched: e-Courts case status, High Court cause lists, tribunal orders",
            "Matches found: 0",
            "Conclusion: Clear - no pending or disposed cases linked to the subject.",
            f"Report date: {dmy(p.court_date)}",
        ]
    return [lines], fields(p.doc_name, p.doc_dob if v == 0 else None, None, p.court_date)


# ----------------------------------------------------------- not documents

def cover_letter(p, v):
    if v == 0:
        lines = [
            "Dear HR Team,",
            "Please find attached my documents for background verification:",
            "Aadhaar card, PAN card, 10th certificate and the other documents you asked for.",
            "Kindly let me know if anything else is required.",
            "Regards,",
            p.name,
            p.phone,
        ]
    else:
        lines = [
            "Hi,",
            "PFA the documents requested in your last email.",
            "Thanks and regards,",
            p.name,
        ]
    return [lines], fields(p.name)


def blank_page(p, v):
    text = "This page is intentionally left blank." if v == 0 else "Scanned with a document scanner app"
    return [[text]], fields(None)


TEMPLATES = {
    "aadhaar": (aadhaar, 2),
    "pan": (pan, 2),
    "passport": (passport, 2),
    "driving_license": (driving_license, 2),
    "voter_id": (voter_id, 2),
    "10th_certificate": (tenth, 3),
    "12th_certificate": (twelfth, 3),
    "marksheet": (marksheet, 2),
    "degree_certificate": (degree, 2),
    "provisional_certificate": (provisional, 2),
    "offer_letter": (offer_letter, 2),
    "experience_letter": (experience_letter, 2),
    "relieving_letter": (relieving_letter, 2),
    "payslip": (payslip, 2),
    "form_16": (form_16, 2),
    "bank_statement": (bank_statement, 2),
    "bgv_consent": (bgv_consent, 2),
    "police_verification": (police_verification, 2),
    "court_record": (court_record, 2),
    # true label "unknown": pages that are not a verification document
    "cover_letter": (cover_letter, 2),
    "blank_page": (blank_page, 2),
}

NOT_A_DOCUMENT = {"cover_letter", "blank_page"}
