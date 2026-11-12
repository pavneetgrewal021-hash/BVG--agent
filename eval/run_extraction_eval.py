"""
Scores field extraction (name, dob, doc_number, issue_date) on the synthetic set.

    python eval/run_extraction_eval.py --split dev --model qwen3:4b

Every document is given with its true pages and true type, so this measures
extraction alone, not classification. Three methods on the same documents:
  regex   rules only (baseline)
  llm     raw model answer
  hybrid  model answer + code checks (what the app uses)
doc_number is scored only for ID documents, where the number is well defined.
"""
import argparse
import json
import os
import sys
import time
from datetime import date

os.environ.setdefault("BGV_DB_PATH", ":memory:")  # set before importing the app, so data/bgv.db is never touched
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import extractor
from services import validators as v
from services.document_classifier import extract_page_texts

DATA_DIR = os.path.join(ROOT, "eval", "data")
RESULTS_DIR = os.path.join(ROOT, "eval", "results")
METHODS = ["regex", "llm", "hybrid"]


def same(field, pred, truth):
    if field == "name":
        return v.normalise_name(pred) == v.normalise_name(truth)
    if field in ("dob", "issue_date"):
        return v.parse_date(pred) == date.fromisoformat(truth)
    return v.compact(pred) == v.compact(truth)


def outcome(field, doc_type, pred, truth):
    """correct | wrong | missing | invented | correct_null | not_scored"""
    if field == "doc_number" and doc_type not in extractor.IDENTITY_TYPES:
        return "not_scored"
    if truth is None:
        return "invented" if pred else "correct_null"
    if not pred:
        return "missing"
    return "correct" if same(field, pred, truth) else "wrong"


def summarise(rows, method):
    out = {}
    for field in extractor.FIELDS + ["all"]:
        cells = [r["outcomes"][method][f] for r in rows for f in extractor.FIELDS
                 if field in ("all", f) and r["outcomes"][method][f] != "not_scored"]
        count = {k: cells.count(k) for k in ("correct", "wrong", "missing", "invented", "correct_null")}
        printed = count["correct"] + count["wrong"] + count["missing"]
        answered = count["correct"] + count["wrong"] + count["invented"]
        out[field] = {**count,
                      "accuracy": count["correct"] / printed if printed else None,
                      "bad_answer_rate": (count["wrong"] + count["invented"]) / answered if answered else None}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--model", default="qwen3:4b")
    args = parser.parse_args()
    settings = {"classifier": "llm", "llm_provider": "ollama", "llm_model": args.model}

    with open(os.path.join(DATA_DIR, "labels.json")) as f:
        labels = json.load(f)

    rows, llm_seconds, errors = [], [], 0
    for cand in labels["candidates"]:
        if cand["split"] != args.split:
            continue
        texts = extract_page_texts(os.path.join(DATA_DIR, cand["pdf"]))
        for doc in cand["documents"]:
            if doc["doc_type"] == "unknown":
                continue
            text = "\n".join(texts[p] for p in doc["pages"])
            truth = doc["fields"]

            preds = {"regex": extractor.regex_extract(doc["doc_type"], text)}
            start = time.perf_counter()
            try:
                raw, _ = extractor.llm_extract(doc["doc_type"], text, settings)
            except extractor.LLMError as e:
                errors += 1
                print(f"  LLM error on {doc['doc_id']}: {e}")
                raw = dict.fromkeys(extractor.FIELDS)
            llm_seconds.append(time.perf_counter() - start)
            checked = extractor.fill_gaps_from_regex(extractor.check_fields(doc["doc_type"], raw, text),
                                                     doc["doc_type"], text)
            preds["llm"] = raw
            preds["hybrid"] = {f: checked[f]["value"] for f in extractor.FIELDS}

            rows.append({
                "doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "scanned": doc["scanned"],
                "truth": truth, "preds": preds,
                "checks": {f: {"status": checked[f]["status"], "source": checked[f]["source"],
                               "note": checked[f]["note"]} for f in extractor.FIELDS},
                "outcomes": {m: {f: outcome(f, doc["doc_type"], preds[m][f], truth[f]) for f in extractor.FIELDS}
                             for m in METHODS},
            })

    summary = {"split": args.split, "model": args.model, "prompt_version": extractor.PROMPT_VERSION,
               "checks_version": extractor.CHECKS_VERSION,
               "documents": len(rows), "llm_errors": errors,
               "seconds_per_document": sum(llm_seconds) / len(llm_seconds) if llm_seconds else 0,
               "methods": {m: summarise(rows, m) for m in METHODS}}

    # How many bad raw LLM values did the checks remove or repair?
    bad_raw = [(r, f) for r in rows for f in extractor.FIELDS if r["outcomes"]["llm"][f] in ("wrong", "invented")]
    fixed = [(r, f) for r, f in bad_raw if r["outcomes"]["hybrid"][f] in ("correct", "correct_null", "missing")]
    broken = [(r, f) for r in rows for f in extractor.FIELDS
              if r["outcomes"]["llm"][f] == "correct" and r["outcomes"]["hybrid"][f] != "correct"]
    summary.update(bad_llm_values=len(bad_raw), removed_or_repaired_by_checks=len(fixed),
                   correct_values_lost_to_checks=len(broken))

    print(f"\n=== Extraction on {args.split}: {len(rows)} documents, model {args.model}, prompt {extractor.PROMPT_VERSION} ===")
    print(f"LLM time {summary['seconds_per_document']:.2f} s/document, errors {errors}\n")
    print(f"{'field':11} {'method':7} {'accuracy':>9} {'correct':>8} {'wrong':>6} {'missing':>8} {'invented':>9} {'bad answers':>12}")
    for field in extractor.FIELDS + ["all"]:
        for m in METHODS:
            s = summary["methods"][m][field]
            acc = f"{s['accuracy']:.1%}" if s["accuracy"] is not None else "-"
            bad = f"{s['bad_answer_rate']:.1%}" if s["bad_answer_rate"] is not None else "-"
            print(f"{field:11} {m:7} {acc:>9} {s['correct']:>8} {s['wrong']:>6} {s['missing']:>8} {s['invented']:>9} {bad:>12}")
        print()
    print(f"Bad raw LLM values: {len(bad_raw)}; removed or repaired by the checks: {len(fixed)}; "
          f"correct values lost to the checks: {len(broken)}")

    print("\nRemaining hybrid mistakes:")
    for r in rows:
        for f in extractor.FIELDS:
            if r["outcomes"]["hybrid"][f] in ("wrong", "invented"):
                print(f"  {r['doc_id']} {r['doc_type']:20} {f:10} got {r['preds']['hybrid'][f]!r} truth {r['truth'][f]!r}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"extraction-{args.model.replace(':', '-')}_{args.split}.json")
    with open(out, "w") as f:
        json.dump({"summary": summary, "documents": rows}, f, indent=2)
    print(f"\nSaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
