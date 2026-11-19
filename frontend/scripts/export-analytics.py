"""Export only allowlisted aggregate scientific results; never load images/weights.

Run from any directory. --check compares the versioned export without writing.
Source modified dates are filesystem provenance, not inferred evaluation dates.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "frontend/src/data/experiments.json"
MODELS = ("B0", "A1", "T0", "T1", "T2")
CATEGORIES = ("bottle", "hazelnut", "leather")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ratio(a, b):
    return a / b if b else None


def decisions(counts):
    tp, tn, fp, fn = (counts[k] for k in ("tp", "tn", "fp", "fn"))
    return {"precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "fpr": ratio(fp, fp + tn), "accuracy": ratio(tp + tn, tp + tn + fp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn)}


def synthetic_metrics(rows, threshold):
    """Group tied archived scores; no fitting or new threshold selection."""
    counts = {k: 0 for k in ("tp", "tn", "fp", "fn")}
    groups = {}
    for row in rows:
        label, score = row["label"], row["score"]
        if label not in (0, 1) or row["split"] != "val":
            raise ValueError("Synthetic reference must contain validation only")
        counts[("tp" if label else "fp") if score > threshold else ("fn" if label else "tn")] += 1
        groups.setdefault(score, [0, 0])[label] += 1
    positives, negatives = counts["tp"] + counts["fn"], counts["tn"] + counts["fp"]
    tp = fp = 0
    area = ap = 0.0
    for score in sorted(groups, reverse=True):
        n, p = groups[score]
        # trapezoidal AUROC in counts; tied pairs contribute one half.
        area += n * (tp + p / 2)
        tp += p
        fp += n
        if positives:
            ap += p / positives * tp / (tp + fp)
    return {**decisions(counts), "auroc": ratio(area, positives * negatives),
            "ap": ap if positives else None, "images": len(rows), "confusion": counts}


def build(root=ROOT):
    sources = {}

    def read(path, purpose):
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        sources[relative] = {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                             "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                             "purpose": purpose}
        return json.loads(raw)

    records = []
    for model in MODELS:
        for category in CATEGORIES:
            transfer = model.startswith("T")
            pattern = (f"reports/transfer/evaluation/{model}/{category}/seed42/*/*/metrics.json" if transfer
                       else f"reports/evaluation/{model.lower()}/*/{category}/metrics.json")
            candidates = sorted(root.glob(pattern))
            if len(candidates) != 1:
                raise ValueError(f"Exactly one official report required for {model}/{category}, found {len(candidates)}")
            path = candidates[0]
            report = read(path, "official_test_metrics")
            metrics = report["metrics"]
            if report["category"] != category or report["split"] != ("test_real_mvtec" if transfer else "test"):
                raise ValueError("Unexpected official report identity/split")
            counts = {key: metrics[key] if transfer else metrics["image_decision"][key] for key in ("tp", "tn", "fp", "fn")}
            ranking = metrics if transfer else metrics["image"]
            image = {**decisions(counts), "f1": metrics["f1"] if transfer else metrics["image_decision"]["f1"],
                     "auroc": ranking["auroc"], "ap": ranking["ap"]}
            record = {"model": model, "category": category, "seed": 42,
                      "images": report["images"] if transfer else metrics["images"],
                      "split": report["split"], "evaluation_date": None,
                      "protocol_sha256": report["protocol_sha256"],
                      "threshold": report["image_threshold"], "image": image, "confusion": counts,
                      "pixel": None if transfer else {"auroc": metrics["pixel"]["auroc"], "ap": metrics["pixel"]["ap"],
                                                       "dice": metrics["segmentation_micro"]["dice"], "iou": metrics["segmentation_micro"]["iou"]},
                      "source": path.relative_to(root).as_posix(), "synthetic_validation": None,
                      "parameters": {"total": None, "trainable": None, "source": None}}
            if sum(counts.values()) != record["images"]:
                raise ValueError("Confusion counts do not cover official test images")
            if transfer:
                if report["status"] != "passed" or report["test_executed"] is not True:
                    raise ValueError("Transfer test report is not completed")
                record["synthetic_validation"] = synthetic_metrics(report["validation_scores"], report["image_threshold"])
                summaries = list(root.glob(f"artifacts/transfer_runs/{model}/{category}/seed42/full_*/summary.json"))
                if len(summaries) != 1:
                    raise ValueError("Ambiguous full training summary")
                summary = read(summaries[0], "architecture_parameter_counts")
                if summary["checkpoint_sha256"] != report["checkpoint_sha256"]:
                    raise ValueError("Architecture summary/checkpoint binding mismatch")
                params = summary["trainable_parameters"]
                record["parameters"] = {"total": params["total_parameters"], "trainable": params["trainable_parameters"],
                                        "source": summaries[0].relative_to(root).as_posix()}
            else:
                param_path = root / ("reports/experiments/b0_architecture_smoke.json" if model == "B0"
                                     else "reports/experiments/a1_implementation_verification.json")
                params = read(param_path, "architecture_parameter_count_only_not_performance")
                record["parameters"] = {"total": params["architecture"]["parameters_total"] if model == "B0" else params["parameters"],
                                        "trainable": params["architecture"]["parameters_trainable"] if model == "B0" else None,
                                        "source": param_path.relative_to(root).as_posix()}
            records.append(record)
    diagnostic = root / "reports/experiments/b0_a1_diagnostic.md"
    sources[diagnostic.relative_to(root).as_posix()] = {
        "path": diagnostic.relative_to(root).as_posix(), "sha256": digest(diagnostic),
        "modified_utc": datetime.fromtimestamp(diagnostic.stat().st_mtime, timezone.utc).isoformat(),
        "purpose": "post_hoc_diagnostic_context_only", "document_date": "2026-11-13"}
    macro = []
    for model in MODELS:
        rows = [r for r in records if r["model"] == model]
        macro.append({"model": model, "categories": len(rows), "image": {
            metric: sum(r["image"][metric] for r in rows) / len(rows)
            if all(r["image"][metric] is not None for r in rows) else None
            for metric in ("auroc", "ap", "f1", "precision", "recall", "fpr", "accuracy")}})
    return {"schema_version": 1, "categories": list(CATEGORIES), "models": list(MODELS),
            "records": records, "macro": macro, "sources": list(sources.values()),
            "conditions": {"seed": 42, "input_size": [256, 256], "decision": "score > threshold",
                           "macro": "Unweighted arithmetic mean over the three categories; no score pooling",
                           "derived": "Precision, recall, FPR and accuracy from archived confusion counts; synthetic metrics from archived validation scores at the fixed threshold",
                           "dates": "Evaluation dates absent in source JSON are null; modified_utc describes file metadata only"},
            "limitations": ["Trois catégories étudiées, seed 42.",
                            "Anomalies synthétiques pour l'apprentissage et la validation Transfer Learning.",
                            "Le test réel a déjà été consulté ; absence de validation indépendante après sélection du modèle.",
                            "Grad-CAM est une attribution relative, pas une segmentation.",
                            "Métriques pixel et segmentation uniquement pour B0/A1 ; aucun score AE/sigmoid fusionné.",
                            "Les paramètres A1 entraînables ne sont pas chiffrés dans les sources retenues."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = build()
    content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    # Public export must never contain machine paths or raw per-image records.
    if any(token in content for token in ("C:\\", "/kaggle/", "image_path", "sample_id", "base64", "best.pt")):
        raise ValueError("Unsafe data in public export")
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("Analytics export differs from authenticated aggregate sources")
        print("Verified 15 authentic aggregate records; source files untouched.")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"Exported {len(data['records'])} aggregate records, {len(data['sources'])} sources")


if __name__ == "__main__":
    main()
