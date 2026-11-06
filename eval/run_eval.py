"""
Runs a classifier over the synthetic set and scores it.

    python eval/run_eval.py --split dev --method keyword
    python eval/run_eval.py --split dev --method llm --model qwen3:4b

Writes eval/results/<name>_<split>.json (summary + every page prediction).
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
from services import ai_classifier
from services.document_classifier import extract_page_texts, keyword_classify_text
from services.pipeline import compute_status

DATA_DIR = os.path.join(ROOT, "eval", "data")
RESULTS_DIR = os.path.join(ROOT, "eval", "results")


def keyword_method(pdf_path, model):
    """The original production classifier, unchanged."""
    texts = extract_page_texts(pdf_path)
    return [keyword_classify_text(t) for t in texts], ai_classifier.keyword_documents(texts), None


def llm_method(pdf_path, model):
    settings = {"classifier": "llm", "llm_provider": "ollama", "llm_model": model}
    documents, page_results = ai_classifier.classify_pdf(pdf_path, settings, log=lambda m: None)
    return [r["doc_type"] for r in page_results], documents, page_results


METHODS = {"keyword": keyword_method, "llm": llm_method}


def evaluate(split, method_name, model):
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
        preds, predicted_docs, details = method(os.path.join(DATA_DIR, cand["pdf"]), model)
        seconds = time.perf_counter() - start
        total_seconds += seconds

        for i, (t, p) in enumerate(zip(truth, preds)):
            row = {"candidate": cand["candidate_id"], "page": i, "true": t, "pred": p, "scanned": scanned[i]}
            if details:
                d = details[i]
                row.update(method=d["method"], confidence=d["confidence"], evidence=d["evidence"],
                           evidence_found=d["evidence_found"],
                           continues_previous_page=d["continues_previous_page"], error=d["error"])
            pages.append(row)

        predicted_types = {d["doc_type"] for d in predicted_docs}
        pred_status, _, _ = compute_status(required, predicted_types)
        real_docs = [d for d in cand["documents"] if d["doc_type"] != "unknown"]
        recovered = [metrics.document_recovered(d, predicted_docs) for d in real_docs]
        candidates.append({
            "candidate": cand["candidate_id"], "true_status": cand["true_status"],
            "pred_status": pred_status, "seconds": round(seconds, 2),
            "docs": len(real_docs), "docs_recovered": sum(recovered),
        })

    pairs = [(r["true"], r["pred"]) for r in pages]
    classes = metrics.per_class(pairs)
    status_pairs = [(c["true_status"], c["pred_status"]) for c in candidates]

    summary = {
        "method": method_name, "model": model if method_name == "llm" else None, "split": split,
        "prompt_version": ai_classifier.PROMPT_VERSION if method_name == "llm" else None,
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
    if method_name == "llm":
        llm_pages = [r for r in pages if r["method"] == "llm"]
        summary.update(
            fallback_pages=len(pages) - len(llm_pages),
            evidence_found_rate=(sum(bool(r["evidence_found"]) for r in llm_pages) / len(llm_pages)
                                 if llm_pages else None),
            calibration=metrics.calibration([(r["confidence"], r["true"] == r["pred"]) for r in llm_pages]),
        )
    return summary, classes, metrics.top_confusions(pairs), candidates, pages


def print_report(summary, classes, confusions, candidates):
    s = summary
    name = s["method"] + (f" ({s['model']}, prompt {s['prompt_version']})" if s["model"] else "")
    print(f"\n=== {name} on {s['split']}: {s['candidates']} candidates, {s['pages']} pages "
          f"({s['pages_digital']} digital, {s['pages_scanned']} scanned) ===")
    print(f"Page accuracy        {s['page_accuracy']:.1%}   (digital {s['page_accuracy_digital']:.1%}, "
          f"scanned {s['page_accuracy_scanned']:.1%})")
    print(f"Macro F1             {s['macro_f1']:.3f}")
    print(f"Documents recovered  {s['documents_recovered']}/{s['documents']}")
    print(f"Status accuracy      {s['status_accuracy']:.1%}   false 'Completed': {s['false_completed']}")
    print(f"Time                 {s['seconds_per_page']:.2f} s/page")
    if "calibration" in s:
        print(f"Fallback pages       {s['fallback_pages']}")
        print(f"Evidence on page     {s['evidence_found_rate']:.1%} of LLM answers")
        print("Confidence band -> accuracy:")
        for b in s["calibration"]:
            acc = f"{b['accuracy']:.0%}" if b["accuracy"] is not None else "-"
            print(f"  {b['band']}: {b['pages']:3} pages, {acc} correct")

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
    parser.add_argument("--model", default="qwen3:4b", help="Ollama model for --method llm")
    args = parser.parse_args()

    summary, classes, confusions, candidates, pages = evaluate(args.split, args.method, args.model)
    print_report(summary, classes, confusions, candidates)

    name = args.method if args.method != "llm" else "llm-" + args.model.replace(":", "-")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"{name}_{args.split}.json")
    with open(out, "w") as f:
        json.dump({"summary": summary, "per_class": classes,
                   "confusions": [[t, p, n] for (t, p), n in confusions],
                   "candidates": candidates, "pages": pages}, f, indent=2)
    print(f"\nSaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
