"""Scoring functions. Pure Python so every number can be traced by hand."""
from collections import Counter


def accuracy(pairs):
    """pairs: list of (true, predicted)."""
    return sum(t == p for t, p in pairs) / len(pairs) if pairs else 0.0


def per_class(pairs):
    """
    For each label:
      precision = of the pages we CALLED this label, how many really were it
      recall    = of the pages that really ARE this label, how many we found
      f1        = harmonic mean of the two (low if either is low)
    """
    labels = sorted({t for t, _ in pairs} | {p for _, p in pairs})
    out = {}
    for label in labels:
        tp = sum(t == label and p == label for t, p in pairs)
        fp = sum(t != label and p == label for t, p in pairs)
        fn = sum(t == label and p != label for t, p in pairs)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    return out


def macro_f1(classes):
    """Average F1 over labels that actually occur in the ground truth, each label weighted equally."""
    present = [c["f1"] for c in classes.values() if c["support"] > 0]
    return sum(present) / len(present) if present else 0.0


def top_confusions(pairs, n=10):
    return Counter((t, p) for t, p in pairs if t != p).most_common(n)


def document_recovered(doc, page_preds, all_docs):
    """
    A document counts as recovered only if the pipeline would produce exactly
    its pages as one file: every page gets its true type, and no page from
    another document in the same PDF gets that type too (the pipeline merges
    all pages of one type into a single file).
    """
    if any(page_preds[i] != doc["doc_type"] for i in doc["pages"]):
        return False
    same_type_pages = {i for i, p in enumerate(page_preds) if p == doc["doc_type"]}
    return same_type_pages == set(doc["pages"])
