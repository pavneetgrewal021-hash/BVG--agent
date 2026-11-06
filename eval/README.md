# Evaluation set

A small, fully synthetic test set for measuring the document classifier, so every
"before vs after" number in this project comes from the same, repeatable test.

```bash
python eval/generate_dataset.py                    # builds eval/data/ (git-ignored, ~12 MB)
python eval/run_eval.py --split dev  --method keyword
python eval/run_eval.py --split test --method keyword
```

Results are saved to `eval/results/<method>_<split>.json`.

## What is in it

| | dev | test | total |
|---|---|---|---|
| Fake candidates (one combined PDF each) | 5 | 10 | 15 |
| Documents (incl. cover letters / blank pages) | 23 | 47 | 70 |
| Pages | 27 | 47 | 74 |
| Scanned documents (image-only, needs OCR) | 12 | 23 | 35 |

- **19 document types** plus two kinds of page that are not documents (cover letter,
  blank page), which have the true label `unknown`.
- **Ground truth comes from the generator**, not from anyone labelling by hand: the
  generator knows exactly which template made which page.
- **Each candidate is one combined PDF**, the way a real candidate emails documents.
  That is what the production pipeline receives.
- **Scans:** 40% of documents are re-rendered as image-only pages, slightly rotated,
  blurred, with noise and JPEG compression, so the Tesseract path really runs.
- **Planted problems for later consistency checks:** one PAN with a different DOB (dev),
  one 10th certificate with a different DOB and one Aadhaar belonging to a different
  person (test), plus two degree certificates that print the name as initials (a
  legitimate variant that must *not* be flagged).
- **Field ground truth** (name, DOB, document number, issue date) is stored for every
  document, ready for the extraction phase.
- All values are invented and every page carries a `SPECIMEN - SYNTHETIC TEST DATA`
  watermark and footer. ID numbers follow the real formats (Aadhaar with a valid
  Verhoeff check digit, PAN with `P` and the surname initial) so validators can be
  tested later. Universities, schools, companies and banks are fictional; government
  issuers keep their real names because that is the text a classifier sees.

### Dev vs test

Every template has 2-3 wordings. **Dev uses wording 0 only; test uses wordings 1+.**
Prompts and rules may be tuned on dev; test is only *run*, never used for tuning.
So test numbers measure documents the system was not tuned on.

## Metrics

| Metric | Meaning |
|---|---|
| Page accuracy | share of pages given the correct type |
| Macro F1 | F1 per type, averaged with every type weighted equally, so rare types count as much as common ones |
| Documents recovered | the pipeline would produce exactly that document's pages as one file (all pages right, nothing else merged in) |
| Status accuracy | the Completed / Partial / Failed result matches the truth (required: Aadhaar, PAN, 10th) |
| False "Completed" | marked Completed when it is not: the most dangerous error for a verification system |
| s/page | wall-clock classification time on the developer laptop |

## Baseline: current keyword classifier

| | dev | **test** |
|---|---|---|
| Page accuracy | 70.4% (19/27) | **66.0% (31/47)** |
| Macro F1 | 0.487 | **0.511** |
| Documents recovered | 12/22 | **22/45** |
| Status accuracy | 2/5 | **7/10** |
| False "Completed" | 2 | **0** |
| Time | 0.84 s/page | 0.74 s/page |

The errors trace back to the classifier's design (first keyword match wins, substring matching):

- University marksheets and provisional certificates become `degree_certificate`
  (keyword "university"); CBSE Class 12 becomes `10th_certificate` ("board of secondary education").
- Any page that *mentions* Aadhaar becomes `aadhaar`: offer letters listing joining
  documents, cover letters, BGV consent forms. On dev this caused both false "Completed" results.
- The back of a degree certificate becomes `aadhaar` ("Enrolment No." is an Aadhaar keyword).
- `nda` matches inside "seco**nda**ry", so an ICSE 10th certificate becomes an NDA.
- Two payslips (or marksheets) are merged into one file.
- Documents worded without the expected phrases (ISC Class 12, a litigation search,
  a police antecedents report) become `unknown`.

## Known limitations (read before quoting numbers)

1. **Synthetic and small.** 74 pages: one page is about 1.4 percentage points on test
   accuracy, and many per-type scores rest on 1-6 pages. Always say "on a synthetic test set".
2. **Scans are too clean.** OCR read the simulated scans almost perfectly, so the gap
   between digital and scanned accuracy reflects *which* documents were scanned, not
   OCR difficulty. Real phone photos are harder.
3. **Designed with knowledge of the classifier.** The templates follow real document
   wording, and the traps above are common in real submissions, but they were written
   by people who knew the keyword list. The mitigation is the unseen-wording test split and
   listing every trap here.
4. **Short documents.** Real documents are longer and messier (tables, stamps, logos, Hindi text).
