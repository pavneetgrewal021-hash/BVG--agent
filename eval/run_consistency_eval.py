"""
Scores the cross-document consistency checks against the planted problems.

    python eval/run_consistency_eval.py --split all --source truth
    python eval/run_consistency_eval.py --split all --source extracted --model qwen3:4b

--source truth      uses the ground-truth fields: tests the matching rules alone
--source extracted  reads the fields with the app's extractor (LLM + checks): end to end
Both name matchers are scored: "exact" (naive baseline) and "smart" (what the app uses).
"""
import argparse
import json
import os
import sys

os.environ.setdefault("BGV_DB_PATH", ":memory:")  # set before importing the app, so data/bgv.db is never touched
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import consistency
from services.document_classifier import extract_page_texts
from services.extractor import extract_document

DATA_DIR = os.path.join(ROOT, "eval", "data")
RESULTS_DIR = os.path.join(ROOT, "eval", "results")
MATCHERS = {"exact": consistency.exact_names_match, "smart": consistency.names_compatible}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "consistency", "all"], default="all")
    parser.add_argument("--source", choices=["truth", "extracted"], default="truth")
    parser.add_argument("--model", default="qwen3:4b")
    args = parser.parse_args()
    settings = {"classifier": "llm", "llm_provider": "ollama", "llm_model": args.model}

    with open(os.path.join(DATA_DIR, "labels.json")) as f:
        labels = json.load(f)

    candidates = []
    for cand in labels["candidates"]:
        if args.split != "all" and cand["split"] != args.split:
            continue
        docs = [d for d in cand["documents"] if d["doc_type"] != "unknown"]
        if args.source == "truth":
            fields = [{"doc_type": d["doc_type"], "name": d["fields"]["name"], "dob": d["fields"]["dob"]}
                      for d in docs]
        else:
            texts = extract_page_texts(os.path.join(DATA_DIR, cand["pdf"]))
            fields = []
            for d in docs:
                got = extract_document(d["doc_type"], "\n".join(texts[p] for p in d["pages"]), settings)["fields"]
                fields.append({"doc_type": d["doc_type"], "name": got["name"]["value"], "dob": got["dob"]["value"]})

        expected = {(f["type"], f["doc_type"]) for f in cand["expected_flags"]}
        variants = {d["doc_type"] for d in docs if d.get("name_variant")}
        row = {"candidate": cand["candidate_id"], "split": cand["split"], "name": cand["name"],
               "fields": fields, "expected": sorted(expected), "legit_variants": sorted(variants)}
        for m, matcher in MATCHERS.items():
            flags = consistency.check_candidate(cand["name"], fields, matcher)
            row[m] = {"flags": flags, "predicted": sorted({(f["type"], f["doc_type"]) for f in flags})}
        candidates.append(row)

    summary = {"split": args.split, "source": args.source,
               "model": args.model if args.source == "extracted" else None,
               "candidates": len(candidates),
               "expected_flags": sum(len(c["expected"]) for c in candidates),
               "legit_name_variants": sum(len(c["legit_variants"]) for c in candidates)}
    for m in MATCHERS:
        tp = fp = fn = variant_alarms = 0
        review = {"right": 0, "missed": 0, "false_alarm": 0}
        for c in candidates:
            exp, pred = set(map(tuple, c["expected"])), set(map(tuple, c[m]["predicted"]))
            tp += len(exp & pred)
            fp += len(pred - exp)
            fn += len(exp - pred)
            variant_alarms += sum(1 for t, d in pred - exp if t == "name_mismatch" and d in c["legit_variants"])
            if bool(exp) == bool(pred):
                review["right"] += 1
            elif exp:
                review["missed"] += 1
            else:
                review["false_alarm"] += 1
        summary[m] = {"caught": tp, "missed": fn, "false_flags": fp,
                      "false_flags_on_legit_name_variants": variant_alarms,
                      "precision": tp / (tp + fp) if tp + fp else None,
                      "recall": tp / (tp + fn) if tp + fn else None,
                      "candidate_review_decision": review}

    print(f"\n=== Consistency checks on {args.split} ({summary['candidates']} candidates), "
          f"fields from {args.source}{' / ' + args.model if summary['model'] else ''} ===")
    print(f"Planted problems: {summary['expected_flags']}   legitimate name variants: {summary['legit_name_variants']}\n")
    print(f"{'matcher':8} {'caught':>7} {'missed':>7} {'false flags':>12} {'on variants':>12} "
          f"{'precision':>10} {'recall':>7}   review decision right / missed / false alarm")
    for m in MATCHERS:
        s = summary[m]
        p = f"{s['precision']:.0%}" if s["precision"] is not None else "-"
        r = f"{s['recall']:.0%}" if s["recall"] is not None else "-"
        d = s["candidate_review_decision"]
        print(f"{m:8} {s['caught']:>7} {s['missed']:>7} {s['false_flags']:>12} "
              f"{s['false_flags_on_legit_name_variants']:>12} {p:>10} {r:>7}   "
              f"{d['right']} / {d['missed']} / {d['false_alarm']}")

    print("\nSmart matcher, every candidate with a planted problem or a flag:")
    for c in candidates:
        exp, pred = set(map(tuple, c["expected"])), set(map(tuple, c["smart"]["predicted"]))
        if exp or pred:
            mark = "OK " if exp == pred else "!! "
            print(f"  {mark}{c['candidate']}: expected {sorted(exp) or '-'}")
            for f in c["smart"]["flags"]:
                print(f"       flagged {f['type']} on {f['doc_type']}: {f['detail']}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    name = f"consistency-{args.source}" + (f"-{args.model.replace(':', '-')}" if summary["model"] else "")
    out = os.path.join(RESULTS_DIR, f"{name}_{args.split}.json")
    with open(out, "w") as f:
        json.dump({"summary": summary, "candidates": candidates}, f, indent=2, default=list)
    print(f"\nSaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
