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

## Local LLM classifier (Phase 2)

`services/ai_classifier.py` sends each page's text to a local model through Ollama
(`qwen3:4b`, thinking off, temperature 0, 4096-token context, JSON output constrained to a
schema with the 32 document types + `unknown`). The model also says whether a page
continues the previous one, so separate documents of one type can be split. If the
model fails for a page, that page falls back to the keyword rules.

```bash
python eval/run_eval.py --split test --method llm --model qwen3:4b
```

### How it was tuned (dev only)

| Prompt | Change | qwen3:4b on dev: page acc. / macro F1 / docs recovered |
|---|---|---|
| v1 | first version | 74.1% / 0.626 / 11 of 22 |
| v2 | accept "continues previous page" only when the model's own type agrees with the previous page (v1 copied the previous type, so one mistake spread to the next pages); sharper descriptions for school-board vs university documents; evidence must quote the title or issuer | 92.6% / 0.905 / 18 of 22 |

Tuning stopped at v2 to avoid fitting the 27 dev pages. Rule 1 of the prompt ("classify
by what the page is, not what it mentions") targets the "mentions Aadhaar" failure seen in
the Phase 1 baseline analysis.

**Model choice was made on dev, before running test:** qwen3:4b (92.6% / 0.905 / 18 of 22)
over phi4-mini (88.9% / 0.837 / 15 of 22).

### Results on the test split (run once, no changes afterwards)

| | Keyword (before) | **qwen3:4b, v2** | phi4-mini, v2 |
|---|---|---|---|
| Page accuracy | 66.0% (31/47) | **97.9% (46/47)** | 91.5% (43/47) |
| Macro F1 | 0.511 | **0.983** | 0.889 |
| Documents recovered | 22/45 | **40/45** | 37/45 |
| Status accuracy | 7/10 | **10/10** | 9/10 |
| False "Completed" | 0 | **0** | 0 |
| Evidence quote found on page | - | 97.9% | 72.3% |
| Time (laptop, RTX 3050 Ti 4 GB) | 0.74 s/page | 3.62 s/page | 3.00 s/page |

Hardware note: neither model fits fully in 4 GB of VRAM (about 55-72% runs on the GPU), so
part of each model runs on the CPU.

### What did not work, and other findings

- **Self-reported confidence is useless here.** Every answer was 0.90 or higher, right or wrong.
- **Token log-probabilities do not work either.** Ollama reports them from before the JSON
  schema restriction is applied, so the forced tokens show near-zero probability whatever the answer.
- **Thinking mode:** on one test page qwen3 took 119 s instead of 1 s and answered wrong. It stays off.
- **Disagreement with the keyword rules is a useful review signal.** On the 48 dev and test pages
  where the two agreed, the LLM was right on all 48. All 3 of its mistakes were on pages
  where they disagreed. They disagree on 26 of 74 pages, so the app shows this as a
  "please review" hint and does not change the status.
- **Remaining failure:** two documents of the same type next to each other (two payslips, two
  marksheets) are usually merged, because the model says the second continues the first.
  This explains 4 of the 5 test documents that were not recovered.

## Field extraction (Phase 3)

`services/extractor.py` reads **name, date of birth, document number and issue date** from
each document, and `services/validators.py` checks them with plain code:

- every value must actually be **printed on the page** (dates in any usual format, so a
  swapped day and month is caught);
- ID numbers must match their **exact format**: Aadhaar with its Verhoeff check digit, PAN
  with holder type `P` and the surname initial, passport, licence, EPIC;
- a DOB must give a plausible age.

A value that fails the on-page or date check is dropped. A value that is on the page but
breaks a rule is kept and flagged. When the model gives nothing usable, a regex value that
passes the same checks fills the gap. Aadhaar numbers are checked in full, then stored and
logged only as `XXXX XXXX 1234`.

```bash
python eval/run_extraction_eval.py --split test --model qwen3:4b
```

Documents are given with their true pages and type, so this measures extraction on its own.
`doc_number` is scored only for ID documents. **Bad answers** = wrong or invented values as a
share of all values returned. In verification a wrong value is worse than a missing one.

### Results on the test split (45 documents, 116 printed values)

| Method | Accuracy | Bad answers |
|---|---|---|
| Regex rules only | 74.1% | 2.3% |
| qwen3:4b, raw | 95.7% | 4.3% |
| **qwen3:4b + code checks** (used by the app) | **100.0% (116/116)** | **0.0%** |
| phi4-mini, raw | 89.7% | 6.3% |
| phi4-mini + code checks | 98.3% | 1.7% |

On test, the checks removed or repaired every bad qwen3:4b value (5 of 5), and 5 of 7 for
phi4-mini. They never removed a correct value. On test, raw phi4-mini got 5 of 15 ID
numbers wrong; with checks it got 15 of 15.

### How the model was chosen (and a process mistake)

1. On dev, with the first checks, qwen3:4b scored 82.0% and phi4-mini 94.0%. qwen3:4b
   often wrote a stray `:` into values (`HARPRE:ET GILL`, `03/07/2:00`). The cause is the model:
   it also happens with plain JSON mode and no schema, and with thinking switched off qwen3
   still writes reasoning into its answer. phi4-mini was picked.
2. Regex gap filling was then added and measured on dev for phi4-mini only (98.0%).
3. Both models were run on test.
4. **Mistake:** step 1 compared the models with different checks. Re-running qwen3:4b on
   dev with the same checks gave 98.0% for both (bad answers 2.0% vs 3.9%). On that fair dev
   tie, the app uses **qwen3:4b for both classification and extraction**, so only one model
   needs to fit in GPU memory. This re-decision was made **after** the test results had been
   seen. Read the extraction test numbers with that in mind.

### Remaining errors and limits

- phi4-mini on test read a court report's name as "Neha Patel, D/O Imran Patel". It passes
  the on-page check because every word is printed on the page.
- A bank statement's period end date was returned as an issue date. Arguably a statement
  date, but the label says none.
- An OCR misreading (`Z5813421` read as `25813421`) cannot be repaired. It is flagged as an
  invalid passport number format.
- **The regex baseline is biased upward.** Its patterns were written knowing the template
  labels, which is why it matches on dev (84%) but drops on the unseen test wording (74%).

## Cross-document consistency checks (Phase 4)

`services/consistency.py` asks whether all of a candidate's documents belong to the same
person. It uses the names and DOBs from Phase 3 and plain code only:

- **name_mismatch.** A document's name must be a plausible way of writing the candidate's
  (Excel) name. Dropping a middle name, using initials, putting the surname first and a
  one-letter OCR slip are allowed. Every word the document prints must fit a *different*
  word of the reference, and the first name and surname must both be present. "Rohan" vs
  "Rahul" does not fit. Text after a relation marker ("D/O ...", "S/O ...") is ignored.
- **dob_mismatch.** Each DOB is compared with the majority DOB. On a tie, the stronger
  document wins (Aadhaar > passport > PAN > 10th...). A document already flagged as someone
  else's does not take part in the DOB vote.

Any flag sets the candidate's status to **Needs Review** instead of Completed. The Review
Queue shows the flags and lets a person **approve** after checking. An approved flag is not
raised again on later runs.

### Evaluation set

A third split, `consistency` (12 candidates, own random seed, so dev and test are
unchanged), was added for this phase. Together with the cases already planted in dev and
test, it gives **10 real problems** and **10 legitimate name variants**:

- Real problems: sibling's PAN, sibling's passport, a stranger's Aadhaar or 10th
  certificate, DOB off by a year, 30 days or 1 day.
- Legitimate variants: middle name dropped or shortened to an initial, initials only,
  surname first.

```bash
python eval/run_consistency_eval.py --split all --source extracted --model qwen3:4b
```

### Results (27 candidates, all splits)

| Name matcher | Problems caught | Missed | False flags | Review decision right |
|---|---|---|---|---|
| Exact match after case and spacing (naive) | 10/10 | 0 | 10 (every legitimate variant) | 21/27 |
| **Smart matcher** (app) | **10/10** | **0** | **0** | **27/27** |

The results are identical with ground-truth fields and with fields read end to end by
qwen3:4b plus checks, because extraction got every name and DOB used here right.

### Limits

- **Small and self-written.** 10 problems and 10 variants, and the same person wrote both
  the scenarios and the matching rules (before running them). Treat 10/10 as "works on the
  cases it was designed for". It is not a measured real-world rate.
- The planted "swapped day and month" became a 1-day shift, because that person's birth
  day (24) cannot be a month. Swap detection at field level is covered by unit tests.
- The relation-marker rule ("D/O ...") was written after Phase 3's test run showed a name
  like "Neha Patel, D/O Imran Patel".
- A person known by their middle name ("Mohan Nair" for "Joseph Mohan Nair") is flagged.
  That is deliberate: a person should check it.

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
5. **Test scored higher than dev for the LLM** (97.9% vs 92.6%). With 47 and 27 pages this is
   within noise, and the test wordings may simply be easier for the model. Do not read it as
   "the model generalises better than it fits".
6. **Prompt rules came from studying failures.** The baseline analysis looked at errors on
   both splits before the prompt was written. Rule 1 is a general domain rule, not specific
   to any template, but it is still knowledge gained partly from test.
