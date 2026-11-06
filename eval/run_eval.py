"""
Runs a classifier over the synthetic set and scores it.

    python eval/run_eval.py --split dev --method keyword

Writes eval/results/<method>_<split>.json (summary + every page prediction).
"""
import argparse
import json
import os
import sys
import time

os.environ.setdefault("BGV_DB_PATH", ":memory:")  # set before importing the pipeline, so data/bgv.db is never touched
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval import metrics
from services.document_classifier import classify_pdf_pages
from services.pipeline import compute_status

DATA_DIR = os.path.join(ROOT, "eval", "data")
RESULTS_DIR = os.path.join(ROOT, "eval", "results")


def keyword_method(pdf_path, n_pages):
    """The current production classifier, unchanged."""
    by_type = classify_pdf_pages(pdf_path)
    preds = ["unknown"] * n_pages
    for doc_type, pages in by_type.items():
        for i in pages:
            preds[i] = doc_type
    return preds


METHODS = {"keyword": keyword_method}


def evaluate(split, method_name):
    with open(os.path.join(DATA_DIR, "labels.json")) as f:
        labels = json.load(f)
    required = labels["required_docs"]
    method = METHODS[method_name]

    pages, candidates = [], []
    total_seconds = 0.0

    for cand in labels["candidates"]:
        if cand["split"] != split:
            continue
        truth = ["unknown"] * cand["pages"]
        scanned = [False] * cand["pages"]
        for doc in cand["documents"]:
            for i in doc["pages"]:
                truth[i] = doc["doc_type"]
                scanned[i] = doc["scanned"]

        start = time.perf_counter()
        preds = method(os.path.join(DATA_DIR, cand["pdf"]), cand["pages"])
        seconds = time.perf_counter() - start
        total_seconds += seconds

        for i, (t, p) in enumerate(zip(truth, preds)):
            pages.append({"candidate": cand["candidate_id"], "page": i, "true": t, "pred": p,
                          "scanned": scanned[i]})

        predicted_types = {p for p in preds if p != "unknown"}
        pred_status, _, _ = compute_status(required, predicted_types)
        real_docs = [d for d in cand["documents"] if d["doc_type"] != "unknown"]
        recovered = [metrics.document_recovered(d, preds, cand["documents"]) for d in real_docs]
        candidates.append({
            "candidate": cand["candidate_id"], "true_status": cand["true_status"],
            "pred_status": pred_status, "seconds": round(seconds, 2),
            "docs": len(real_docs), "docs_recovered": sum(recovered),
        })

    pairs = [(r["true"], r["pred"]) for r in pages]
    classes = metrics.per_class(pairs)
    status_pairs = [(c["true_status"], c["pred_status"]) for c in candidates]

    summary = {
        "method": method_name, "split": split,
        "candidates": len(candidates), "pages": len(pages),
        "page_accuracy": metrics.accuracy(pairs),
        "page_accuracy_digital": metrics.accuracy([(r["true"], r["pred"]) for r in pages if not r["scanned"]]),
        "page_accuracy_scanned": metrics.accuracy([(r["true"], r["pred"]) for r in pages if r["scanned"]]),
        "pages_digital": sum(not r["scanned"] for r in pages),
        "pages_scanned": sum(r["scanned"] for r in pages),
        "macro_f1": metrics.macro_f1(classes),
        "documents": sum(c["docs"] for c in candidates),
        "documents_recovered": sum(c["docs_recovered"] for c in candidates),
        "status_accuracy": metrics.accuracy(status_pairs),
        "false_completed": sum(p == "Completed" and t != "Completed" for t, p in status_pairs),
        "seconds_per_page": total_seconds / len(pages) if pages else 0.0,
    }
    return summary, classes, metrics.top_confusions(pairs), candidates, pages


def print_report(summary, classes, confusions, candidates):
    s = summary
    print(f"\n=== {s['method']} on {s['split']}: {s['candidates']} candidates, {s['pages']} pages "
          f"({s['pages_digital']} digital, {s['pages_scanned']} scanned) ===")
    print(f"Page accuracy        {s['page_accuracy']:.1%}   (digital {s['page_accuracy_digital']:.1%}, "
          f"scanned {s['page_accuracy_scanned']:.1%})")
    print(f"Macro F1             {s['macro_f1']:.3f}")
    print(f"Documents recovered  {s['documents_recovered']}/{s['documents']}")
    print(f"Status accuracy      {s['status_accuracy']:.1%}   false 'Completed': {s['false_completed']}")
    print(f"Time                 {s['seconds_per_page']:.2f} s/page")

    print("\nPer type (support = true pages):")
    print(f"  {'type':24} {'prec':>6} {'recall':>7} {'f1':>6} {'support':>8}")
    for label, c in sorted(classes.items(), key=lambda kv: kv[1]["f1"]):
        print(f"  {label:24} {c['precision']:6.2f} {c['recall']:7.2f} {c['f1']:6.2f} {c['support']:8}")

    print("\nMost common mistakes (true -> predicted):")
    for (t, p), n in confusions:
        print(f"  {n} x  {t} -> {p}")

    print("\nCandidates:")
    for c in candidates:
        mark = "OK " if c["true_status"] == c["pred_status"] else "!! "
        print(f"  {mark}{c['candidate']}: true {c['true_status']:9} predicted {c['pred_status']:9} "
              f"docs recovered {c['docs_recovered']}/{c['docs']}  ({c['seconds']} s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--method", choices=sorted(METHODS), default="keyword")
    args = parser.parse_args()

    summary, classes, confusions, candidates, pages = evaluate(args.split, args.method)
    print_report(summary, classes, confusions, candidates)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"{args.method}_{args.split}.json")
    with open(out, "w") as f:
        json.dump({"summary": summary, "per_class": classes,
                   "confusions": [[t, p, n] for (t, p), n in confusions],
                   "candidates": candidates, "pages": pages}, f, indent=2)
    print(f"\nSaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
