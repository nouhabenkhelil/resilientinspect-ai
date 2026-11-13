"""Audit des archives B0/A1 : aucune construction de modèle ni inférence.

Depuis la racine : .venv/Scripts/python.exe scripts/diagnose_b0_a1.py
Les seules écritures sont le nouveau rapport et son dossier local ignoré.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import platform
from importlib.metadata import version
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from sklearn.metrics import (
    average_precision_score, precision_recall_curve, roc_auc_score, roc_curve,
)
import torch
import yaml

from resilientinspect.data.dataset import letterbox_pair

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("bottle", "hazelnut", "leather")
MODELS = ("b0", "a1")
PROTOCOL = ROOT / "configs/evaluate_ae_b0.yaml"
MANIFEST = ROOT / "data/manifests/manifest.csv"
DATA = ROOT / "data/raw/mvtec_ad"
LOCAL = ROOT / "reports/experiments/b0_a1_diagnostic_local"
REPORT = ROOT / "reports/experiments/b0_a1_diagnostic.md"
SEED, REPLICATES = 42, 2000
NAMES = ("AUROC image", "AP image", "F1 image", "Dice micro", "IoU micro")
ALL_NAMES = (*NAMES, "AUROC pixel", "AP pixel")
FIELDS = ("image_path", "category", "split", "label", "defect_type", "mask_path")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(stream.getvalue(), encoding="utf-8", newline="")


def near(actual, expected, context):
    if actual is None or expected is None:
        require(actual is expected, context)
    else:
        require(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), context)


def overlap(tp, fp, fn):
    return (2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            tp / (tp + fp + fn) if tp + fp + fn else None)


def confusion(rows):
    y = np.array([r["label"] for r in rows])
    p = np.array([r["predicted_label"] for r in rows])
    return {k: int(v.sum()) for k, v in {
        "TP": (y == 1) & (p == 1), "FP": (y == 0) & (p == 1),
        "FN": (y == 1) & (p == 0), "TN": (y == 0) & (p == 0),
    }.items()}


def arrays(rows):
    return np.array([[r[k] for k in ("label", "score", "predicted_label", "tp", "fp", "fn")]
                     for r in rows], dtype=np.float64)


def measurements(a):
    y, score, pred = a[:, 0], a[:, 1], a[:, 2]
    require(np.unique(y).size == 2, "Deux classes requises pour AUROC/AP")
    cm = (np.sum((y == 1) & (pred == 1)), np.sum((y == 0) & (pred == 1)),
          np.sum((y == 1) & (pred == 0)))
    return np.array([roc_auc_score(y, score), average_precision_score(y, score),
                     overlap(*cm)[0], *overlap(*a[:, 3:6].sum(axis=0))])


def protected_inventory():
    # Inclut le premier rapport, toutes les archives officielles, configs, sources,
    # manifestes et checkpoints existants. Les poids sont seulement hachés.
    files = set()
    for folder in ("reports", "configs", "src", "data/manifests"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and not path.is_relative_to(LOCAL) and path != REPORT:
                files.add(path)
    for model in MODELS:
        for category in CATEGORIES:
            report = read_json(ROOT / f"reports/evaluation/{model}/{sha(PROTOCOL)[:12]}/{category}/metrics.json")
            files.add(Path(report["checkpoint"]["path"]))
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in sorted(files)}


def audit_inputs():
    protocol = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    digest = sha(PROTOCOL)
    require(digest == "f515662ab4ef0437194f7fdc7b57c8ea435ae6cb7e1be95c26476a91fa5d963e", "Protocole officiel différent")
    require(sha(MANIFEST) == read_json(MANIFEST.with_name("preparation.json"))["manifest_sha256"][MANIFEST.name], "Manifeste altéré")
    manifest = read_csv(MANIFEST)
    require(len({r["image_path"] for r in manifest}) == len(manifest), "Doublons manifeste")
    test = {r["image_path"]: r for r in manifest if r["split"] == "test"}
    val = {r["image_path"]: r for r in manifest if r["split"] == "val"}
    train = {r["image_path"]: r for r in manifest if r["split"] == "train"}
    require(not (set(test) & set(val) or set(test) & set(train) or set(val) & set(train)), "Splits non disjoints")
    require(not ({r["sha256"] for r in test.values()} & {r["sha256"] for r in (*val.values(), *train.values())}), "Contenu test commun avec train/val")
    require(not ({r["sha256"] for r in val.values()} & {r["sha256"] for r in train.values()}), "Contenu commun train/val")
    require(all(r["source_split"] == "train" and r["label"] == "0" and not r["mask_path"] for r in (*train.values(), *val.values())), "Train/val non normaux")
    dataset_hash = sha(ROOT / "src/data/dataset.py")
    shared_hash = sha(ROOT / "src/evaluation/evaluate_ae.py")
    reports, predictions, checks, masks = {}, {}, [], []
    for category in CATEGORIES:
        expected = {p: r for p, r in test.items() if r["category"] == category}
        expected_val = {p: r for p, r in val.items() if r["category"] == category}
        disk_test = {p.relative_to(DATA).as_posix() for p in (DATA / category / "test").rglob("*.png")}
        require(disk_test == set(expected), f"Test officiel incomplet : {category}")
        for model in MODELS:
            folder = ROOT / f"reports/evaluation/{model}/{digest[:12]}/{category}"
            report, calibration = read_json(folder / "metrics.json"), read_json(folder / "calibration.json")
            for obj in (report, calibration):
                require(obj["category"] == category, "Catégorie JSON")
                require(obj["protocol_sha256"] == digest and obj["manifest_sha256"] == sha(MANIFEST), "Provenance protocole/manifeste")
                require(obj["dataset_code_sha256"] == dataset_hash, "Prétraitement courant différent de celui archivé")
                require(obj.get("shared_evaluation_code_sha256", obj["evaluation_code_sha256"]) == shared_hash, "Code commun différent")
                require(obj["checkpoint_sha256"] == report["checkpoint_sha256"] == sha(Path(report["checkpoint"]["path"])), "Empreinte checkpoint")
                require(obj["checkpoint"] == report["checkpoint"], "Provenance checkpoint calibration/test")
                require(obj["evaluation_code_sha256"] == sha(ROOT / f"src/evaluation/{'evaluate_ae' if model == 'b0' else 'evaluate_a1'}.py"), "Code évaluation différent")
                if "protocol" in obj:
                    require(obj["protocol"] == protocol, "Contenu protocole divergent")
            require(report["split"] == "test" and report["resolution"] == [256, 256] and report["padding_excluded"] is True, "Géométrie/protocole test")
            calibration_hash = sha(folder / "calibration.json")
            require(calibration_hash == (folder / "calibration.sha256").read_text().strip() == report["calibration_sha256"], "Intégrité calibration")
            require(calibration["calibration_split"] == "val" and calibration["normal_only"] is True, "Split calibration")
            scores = calibration["validation_scores"]
            require(len(scores) == len(expected_val) == calibration["validation_images"], "Effectif calibration")
            require({r["image_path"] for r in scores} == set(expected_val), "Images calibration")
            scores_csv = read_csv(folder / "calibration_scores.csv")
            require(len(scores_csv) == len(scores), "Effectif CSV calibration")
            require({r["image_path"]: float(r["score"]) for r in scores_csv} == {r["image_path"]: r["score"] for r in scores}, "CSV/JSON calibration")
            # Vérification de la règle archivée ; aucune écriture de seuil.
            near(float(np.quantile([r["score"] for r in scores], protocol["image_threshold_quantile"], method="higher")), calibration["image_threshold"], "Quantile image validation")
            near(np.mean([r["score"] > calibration["image_threshold"] for r in scores]), calibration["empirical_image_fpr"], "FPR validation image")
            for key in ("image_threshold", "pixel_threshold"):
                require(report[key] == calibration[key], "Seuil rapport/calibration")
            rows = read_csv(folder / "predictions.csv")
            require(len(rows) == len(expected) and len({r["image_path"] for r in rows}) == len(rows), "Effectifs/doublons test")
            require({r["image_path"] for r in rows} == set(expected), "Identifiants test")
            for row in rows:
                require(all(row[k] == expected[row["image_path"]][k] for k in FIELDS), f"Métadonnées image : {row['image_path']}")
                for key in ("label", "predicted_label", "valid_pixels", "tp", "fp", "fn"):
                    row[key] = int(row[key])
                for key in ("score", "image_threshold", "pixel_threshold"):
                    row[key] = float(row[key])
                    require(math.isfinite(row[key]), "Score/seuil non fini")
                require(row["empty_anomalous_mask"] in ("True", "False"), "Flag masque vide")
                row["empty_anomalous_mask"] = row["empty_anomalous_mask"] == "True"
                require(row["predicted_label"] == int(row["score"] > calibration["image_threshold"]), "Décision strictement >")
                require(row["image_threshold"] == calibration["image_threshold"] and row["pixel_threshold"] == calibration["pixel_threshold"], "Seuil CSV")
                require(min(row[k] for k in ("tp", "fp", "fn")) >= 0 and sum(row[k] for k in ("tp", "fp", "fn")) <= row["valid_pixels"], "Comptages pixel impossibles")
                for key, value in zip(("dice", "iou"), overlap(row["tp"], row["fp"], row["fn"])):
                    row[key] = float(row[key]) if row[key] else None
                    near(row[key], value, f"{key} image")
            rows.sort(key=lambda r: r["image_path"])
            predictions[model, category], reports[model, category] = rows, report
            official = report["metrics"]
            require(len(rows) == official["images"] and sum(r["label"] for r in rows) == official["anomalous_images"], "Effectifs rapport")
            require(sum(r["valid_pixels"] for r in rows) == official["valid_pixels"], "Pixels valides rapport")
            require(sum(r["empty_anomalous_mask"] for r in rows) == official["empty_anomalous_masks"], "Masques vides rapport")
            for k, v in confusion(rows).items():
                require(official["image_decision"][k.lower()] == v, "Matrice officielle")
            expected_metrics = [official["image"]["auroc"], official["image"]["ap"], official["image_decision"]["f1"], official["segmentation_micro"]["dice"], official["segmentation_micro"]["iou"]]
            for name, value, reference in zip(NAMES, measurements(arrays(rows)), expected_metrics):
                near(value, reference, f"{model}/{category}/{name}")
            for k in ("tp", "fp", "fn"):
                require(sum(r[k] for r in rows) == official["segmentation_micro"][k], "Comptages segmentation rapport")
            for k in ("dice", "iou"):
                values = [r[k] for r in rows if r["label"] and r[k] is not None]
                near(float(np.mean(values)), official[f"{k}_macro_anomalous"], "Moyenne anomalous")
                require(len(values) == official[f"{k}_macro_anomalous_n"], "Effectif anomalous")
            checks.append({"model": model.upper(), "category": category, "test_images": len(rows), "val_images": len(scores), "image_threshold": calibration["image_threshold"], "pixel_threshold": calibration["pixel_threshold"], "validation_image_fpr": calibration["empirical_image_fpr"], "validation_pixels": calibration["validation_pixels"], "run_id": report["checkpoint"]["run_id"]})
        b, a = (predictions[m, category] for m in MODELS)
        for rb, ra in zip(b, a):
            require(all(rb[k] == ra[k] for k in (*FIELDS, "valid_pixels", "empty_anomalous_mask")), "Appariement B0/A1")
            require(rb["tp"] + rb["fn"] == ra["tp"] + ra["fn"], "Cibles pixel B0/A1")
        # Lecture seule des originaux ; réutilisation exacte de letterbox_pair.
        for path, row in {**expected, **expected_val}.items():
            image_path = DATA / path
            require(sha(image_path) == row["sha256"], f"SHA image : {path}")
            with Image.open(image_path) as im:
                image = im.convert("RGB")
            if path in expected_val:
                continue
            require(row["source_split"] == "test", "Source test")
            require(row["label"] == str(int(row["defect_type"] != "good")), "Label/défaut")
            require(bool(row["mask_path"]) == (row["label"] == "1"), "Présence masque/label")
            if row["mask_path"]:
                mask_path = DATA / row["mask_path"]
                require(sha(mask_path) == row["mask_sha256"], "SHA masque")
                require(row["mask_path"] == f"{category}/ground_truth/{row['defect_type']}/{Path(path).stem}_mask.png", "Identifiant masque")
                with Image.open(mask_path) as im:
                    mask = im.copy()
            else:
                mask = Image.new("L", image.size, 0)
            native_positive = int(np.count_nonzero(np.asarray(mask)))
            transformed = letterbox_pair(image, mask)
            positive = int(transformed["mask"].sum().item())
            valid = int(transformed["valid_mask"].sum().item())
            for model in MODELS:
                record = next(r for r in predictions[model, category] if r["image_path"] == path)
                require(record["tp"] + record["fn"] == positive and record["valid_pixels"] == valid, "Géométrie/cible CSV versus masque redimensionné")
                require(record["empty_anomalous_mask"] == (row["label"] == "1" and positive == 0), "Flag masque vide vs original")
            masks.append({"image_path": path, "mask_path": row["mask_path"], "label": int(row["label"]), "native_positive_pixels": native_positive, "resized_positive_pixels": positive, "valid_pixels": valid, "became_empty": native_positive > 0 and positive == 0})
        # Validation pixel counts follow the same geometry, checked from native dimensions.
        valid_pixels = 0
        for p in expected_val:
            with Image.open(DATA / p) as image:
                w, h = image.size
            scale = min(256 / h, 256 / w)
            valid_pixels += max(1, min(256, math.floor(w * scale + .5))) * max(1, min(256, math.floor(h * scale + .5)))
        require(all(check["validation_pixels"] == valid_pixels for check in checks[-2:]), "Effectif pixels validation")
    # Les moyennes macro officielles doivent aussi correspondre aux six rapports.
    for model in MODELS:
        macro = read_json(ROOT / f"reports/evaluation/{model}/{digest[:12]}/macro_metrics.json")
        for i, key in enumerate(("image_auroc", "image_ap", "image_f1", "dice_micro", "iou_micro", "pixel_auroc", "pixel_ap")):
            near(float(np.mean([official_values(reports[model, c])[i] for c in CATEGORIES])), macro[key]["mean"], "Macro officielle")
            require(macro[key]["categories"] == 3, "Effectif macro")
    return reports, predictions, checks, masks


def official_values(report):
    m = report["metrics"]
    return np.array([m["image"]["auroc"], m["image"]["ap"], m["image_decision"]["f1"], m["segmentation_micro"]["dice"], m["segmentation_micro"]["iou"], m["pixel"]["auroc"], m["pixel"]["ap"]])


def paired_bootstrap(predictions):
    rng = np.random.default_rng(SEED)
    samples = np.empty((len(CATEGORIES), REPLICATES, 2, len(NAMES)))
    for ci, category in enumerate(CATEGORIES):
        b, a = (arrays(predictions[m, category]) for m in MODELS)
        strata = [np.flatnonzero(b[:, 0] == label) for label in (0, 1)]
        for rep in range(REPLICATES):
            indices = np.concatenate([rng.choice(s, size=len(s), replace=True) for s in strata])
            samples[ci, rep, 0] = measurements(b[indices])
            samples[ci, rep, 1] = measurements(a[indices])
        print(f"Bootstrap apparié terminé : {category}", flush=True)
    rows = []
    for category, draws in [*zip(CATEGORIES, samples), ("macro", samples.mean(axis=0))]:
        point = np.array([np.mean([measurements(arrays(predictions[m, c])) for c in CATEGORIES], axis=0) if category == "macro" else measurements(arrays(predictions[m, category])) for m in MODELS])
        for i, name in enumerate(NAMES):
            row = {"category": category, "metric": name}
            for label, values, estimate in (("B0", draws[:, 0, i], point[0, i]), ("A1", draws[:, 1, i], point[1, i]), ("delta", draws[:, 1, i] - draws[:, 0, i], point[1, i] - point[0, i])):
                low, high = np.quantile(values, [.025, .975])
                row.update({label: float(estimate), label + "_low": float(low), label + "_high": float(high)})
            rows.append(row)
    return rows


def defect_metrics(predictions):
    rows = []
    for category in CATEGORIES:
        for model in MODELS:
            population = predictions[model, category]
            normals = [r for r in population if not r["label"]]
            for defect in sorted({r["defect_type"] for r in population if r["label"]}):
                subset = [r for r in population if r["defect_type"] == defect]
                cm = confusion(normals + subset)
                dice, iou = overlap(*(sum(r[k] for r in subset) for k in ("tp", "fp", "fn")))
                score = measurements(arrays(normals + subset))
                rows.append({"category": category, "model": model.upper(), "defect": defect, "anomalous_n": len(subset), "normal_n": len(normals), **cm, "recall": cm["TP"] / len(subset), "image_auroc_vs_good": float(score[0]), "image_ap_vs_good": float(score[1]), "image_f1_vs_good": float(score[2]), "dice_defect_only": dice, "iou_defect_only": iou, "empty_masks": sum(r["empty_anomalous_mask"] for r in subset)})
    return rows


def figures(predictions):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 120})
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.8), layout="constrained")
    for mi, model in enumerate(MODELS):
        for ci, category in enumerate(CATEGORIES):
            ax = axes[mi, ci]
            cm = confusion(predictions[model, category])
            matrix = np.array([[cm["TN"], cm["FP"]], [cm["FN"], cm["TP"]]])
            ax.imshow(matrix, cmap="Blues", vmin=0, vmax=max(matrix.max(), 1))
            for (i, j), v in np.ndenumerate(matrix):
                label = (("TN", "FP"), ("FN", "TP"))[i][j]
                ax.text(j, i, f"{label}\n{v}", ha="center", va="center", color="white" if v > matrix.max() / 2 else "black", fontsize=13)
            ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Normale", "Anormale"], yticklabels=["Normale", "Anormale"], xlabel="Prédiction au seuil validation", ylabel="Vérité terrain", title=f"{model.upper()} — {category}")
    fig.suptitle("Matrices image — anomalie = classe positive")
    fig.savefig(LOCAL / "confusion.png")
    plt.close(fig)
    fig, axes = plt.subplots(3, 2, figsize=(12, 10), layout="constrained")
    for ci, category in enumerate(CATEGORIES):
        all_scores = [r["score"] for m in MODELS for r in predictions[m, category]]
        bins = np.linspace(min(all_scores), max(all_scores), 22)
        ymax = 0
        for mi, model in enumerate(MODELS):
            ax = axes[ci, mi]
            rows = predictions[model, category]
            for label, color, title in ((0, "#2879b9", "Normales"), (1, "#d67822", "Anormales")):
                scores = [r["score"] for r in rows if r["label"] == label]
                heights, _, _ = ax.hist(scores, bins=bins, weights=np.ones(len(scores)) / len(scores), alpha=.55, color=color, label=f"{title} (n={len(scores)})")
                ymax = max(ymax, max(heights))
            threshold = rows[0]["image_threshold"]
            ax.axvline(threshold, color="black", linestyle="--", label=f"Seuil val = {threshold:.6f}")
            ax.set(xlabel="Score image brut (moyenne top 1 % L1)", ylabel="Proportion dans chaque classe", title=f"{model.upper()} — {category}", xlim=(bins[0], max(bins[-1], threshold) * 1.02))
            ax.legend(fontsize=8)
        for ax in axes[ci]:
            ax.set_ylim(0, ymax * 1.2)
    fig.suptitle("Scores test — seuils validation archivés et inchangés ; bins communs par catégorie")
    fig.savefig(LOCAL / "score_distributions.png")
    plt.close(fig)
    for kind in ("roc", "pr"):
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), layout="constrained")
        curve_rows = []
        for category, ax in zip(CATEGORIES, axes):
            for model, color in zip(MODELS, ("#2879b9", "#d67822")):
                rows = predictions[model, category]
                y, s = np.array([r["label"] for r in rows]), np.array([r["score"] for r in rows])
                cm = confusion(rows)
                if kind == "roc":
                    x, z, thresholds = roc_curve(y, s, drop_intermediate=False)
                    label = f"{model.upper()} AUROC={roc_auc_score(y, s):.4f}"
                    point = (cm["FP"] / (cm["FP"] + cm["TN"]), cm["TP"] / (cm["TP"] + cm["FN"]))
                else:
                    z, x, thresholds = precision_recall_curve(y, s)
                    label = f"{model.upper()} AP={average_precision_score(y, s):.4f}"
                    point = (cm["TP"] / (cm["TP"] + cm["FN"]), cm["TP"] / (cm["TP"] + cm["FP"]) if cm["TP"] + cm["FP"] else 0)
                ax.step(x, z, where="post", color=color, label=label) if kind == "pr" else ax.plot(x, z, color=color, label=label)
                ax.scatter(*point, color=color, marker="o", s=38, zorder=3)
                for i in range(len(x)):
                    t = float(thresholds[i]) if i < len(thresholds) else None
                    curve_rows.append({"category": category, "model": model.upper(), "x": float(x[i]), "y": float(z[i]), "threshold": t if t is None or math.isfinite(t) else "inf"})
            if kind == "roc":
                ax.plot([0, 1], [0, 1], "k:", alpha=.5)
                ax.set(xlabel="Taux de faux positifs", ylabel="Rappel / taux de vrais positifs")
            else:
                ax.axhline(y.mean(), color="gray", linestyle=":", label=f"Prévalence={y.mean():.3f}")
                ax.set(xlabel="Rappel", ylabel="Précision")
            ax.set(title=category, xlim=(-.02, 1.02), ylim=(-.02, 1.02))
            ax.legend(fontsize=9, loc="lower right" if kind == "roc" else "lower left")
        fig.suptitle(f"{'ROC' if kind == 'roc' else 'Precision–Recall'} image — points = décisions aux seuils validation figés")
        fig.savefig(LOCAL / f"{kind}.png")
        write_csv(LOCAL / f"{kind}_points.csv", curve_rows)
        plt.close(fig)


def table(headers, rows):
    def cell(v):
        if v is None:
            return "ND"
        return f"{v:.6f}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |", *["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]])


def render_report(reports, predictions, checks, masks, bootstrap, defects, differences, conservation):
    text = ["# Diagnostic scientifique complémentaire B0/A1", "Date : 13 novembre 2026. Audit des archives officielles `f515662ab4ef`, sans entraînement, reconstruction de checkpoint, inférence ou recalibration. Le rapport de premier suivi est conservé.",
    "## Périmètre et statut des analyses",
    "Les résultats du protocole initial restent les six `metrics.json` sous `reports/evaluation/{b0,a1}/f515662ab4ef`. Les AUROC/AP image, F1 image, Dice/IoU micro, AUROC/AP pixel et moyennes par catégorie ci-dessous reprennent ces archives ; les valeurs image et les recouvrements sont aussi recalculés depuis les CSV. Les matrices et distributions visualisent les mêmes décisions. Les courbes n'introduisent aucun seuil opérationnel nouveau.",
    "Les ventilations par défaut, intervalles bootstrap et interprétations diagnostiques sont **post-hoc descriptifs**. Aucun résultat ne sert à sélectionner une variante ou modifier les seuils, hyperparamètres, splits ou protocoles. Les documents de protocole antérieurs décrivaient une étape préparatoire ; leur ancien statut ne remplace pas l'existence des archives finales auditées ici.",
    "## Contrôles d'identité et de provenance",
    f"Tous les contrôles ont réussi : {len(masks)} images test distinctes, {sum(c['val_images'] for c in checks if c['model'] == 'B0')} images validation distinctes. B0 et A1 utilisent exactement les mêmes identifiants, catégories, labels, défauts, chemins de masques, pixels valides et cibles positives après resize. Pas de doublon, image manquante ou supplémentaire face au manifeste et à l'arborescence test PNG. Train/val/test sont disjoints par chemin et SHA256 déclaré ; train et val sont normaux et issus de train officiel. Les SHA256 réels des images test/val et masques test correspondent au manifeste.",
    f"Protocole SHA256 : `{sha(PROTOCOL)}`. Manifeste SHA256 : `{sha(MANIFEST)}`. Codes Dataset et évaluation commune présents identiques à leurs empreintes archivées. Les six checkpoints ont été hachés, sans chargement. Les empreintes des calibrations, leurs compagnons SHA256 et leur liaison checkpoint/manifeste/protocole ont été vérifiés.",
    "Prétraitement commun : RGB [0,1], letterbox 256×256, bilinéaire image, nearest masque ; padding exclu. Carte = erreur absolue RGB moyenne, sans lissage. Score = moyenne des `ceil(0,01 × N_valides)` plus grandes erreurs ; décision **strictement > seuil**. Seuils issus de validation normale : quantile image 0,95 et pixel 0,995, méthode `higher`, propres à chaque modèle/catégorie. Les six seuils image sont retrouvés depuis les scores val archivés ; les seuils pixel sont contrôlés pour intégrité et cohérence, mais leur quantile ne peut pas être recalculé sans les erreurs pixel val absentes des CSV. Aucun recalcul de calibration n'a été exécuté.",
    table(["Modèle", "Catégorie", "n test", "n val", "Seuil image", "Seuil pixel", "FPR image val"], [[c[k] for k in ("model", "category", "test_images", "val_images", "image_threshold", "pixel_threshold", "validation_image_fpr")] for c in checks]),
    "Les effectifs, décisions, agrégats TP/FP/FN, Dice/IoU micro, moyennes par image anormale et moyennes macro correspondent aux JSON (tolérance numérique 1e−12). Les scores pixel continus ne sont pas archivés dans les CSV : AUROC/AP pixel sont repris des JSON, sans prétendre les recalculer ni leur fournir des IC. La réalité de chaque carte prédite ne peut pas être revérifiée sans ses valeurs pixel ; l'audit vérifie ses comptages archivés et sa cible.",
    "## Résultats confirmés aux seuils du protocole initial",
    table(["Catégorie", "Modèle", "TP", "FP", "FN", "TN", "Rappel", "FPR test", "F1"], [[c, m.upper(), *confusion(predictions[m, c]).values(), confusion(predictions[m, c])["TP"] / sum(r["label"] for r in predictions[m, c]), confusion(predictions[m, c])["FP"] / sum(not r["label"] for r in predictions[m, c]), reports[m, c]["metrics"]["image_decision"]["f1"]] for c in CATEGORIES for m in MODELS]),
    "![Matrices de confusion](b0_a1_diagnostic_local/confusion.png)",
    "### Différences A1 − B0",
    "Valeurs absolues, et non pourcentages relatifs. Dice/IoU = segmentation micro sur toutes les images de la catégorie, normales incluses. Macro = moyenne non pondérée des trois catégories ; aucun mélange des scores de modèles/catégories distincts.",
    table(["Catégorie", "Métrique", "B0", "A1", "A1 − B0"], [[r[k] for k in ("category", "metric", "B0", "A1", "delta")] for r in differences]),
    "### Distributions et courbes image",
    "Les histogrammes normalisent séparément chaque classe (somme des hauteurs = 1), avec les mêmes bins B0/A1 par catégorie. Les scores sont des erreurs brutes, pas des probabilités ; leurs amplitudes ne mesurent pas directement la qualité entre modèles. Les lignes verticales sont les seuils validation archivés.",
    "![Distributions](b0_a1_diagnostic_local/score_distributions.png)",
    "ROC et PR utilisent les scores continus ; les points indiquent les décisions strictes au seuil val. AP est la moyenne de précision non interpolée scikit-learn, pas l'aire trapézoïdale PR. La ligne de prévalence rappelle le déséquilibre des classes. Aucune optimisation de F1 ou de seuil sur test.",
    "![ROC](b0_a1_diagnostic_local/roc.png)", "![Precision–Recall](b0_a1_diagnostic_local/pr.png)",
    "## Analyse post-hoc par type de défaut",
    "AUROC/AP/F1 « vs good » comparent chaque défaut aux mêmes images normales de sa catégorie. Les normales sont réutilisées entre sous-groupes : les lignes ne sont pas des réplications indépendantes et ne doivent pas être sommées. TP/FN/rappel portent sur le défaut ; FP/TN portent sur les normales communes. Dice/IoU de cette table agrègent seulement les images du défaut (leurs FP pixel inclus), donc excluent les FP pixel des normales ; ils ne remplacent pas la segmentation primaire toutes images. Une AUROC sur le seul sous-groupe anormal serait indéfinie.",
    table(["Catégorie", "Modèle", "Défaut", "n défaut", "TP", "FN", "FP good", "TN good", "Rappel", "AUROC vs good", "AP vs good", "F1 vs good", "Dice défaut", "IoU défaut"], [[r[k] for k in ("category", "model", "defect", "anomalous_n", "TP", "FN", "FP", "TN", "recall", "image_auroc_vs_good", "image_ap_vs_good", "image_f1_vs_good", "dice_defect_only", "iou_defect_only")] for r in defects]),
    "### Masques après redimensionnement",
    f"Contrôle direct avec `letterbox_pair` existant : {sum(r['label'] for r in masks)} masques anormaux, {sum(r['became_empty'] for r in masks)} devenu(s) vide(s), {sum(r['label'] == 1 and r['resized_positive_pixels'] == 0 for r in masks)} vide(s) après resize au total. Les pixels positifs redimensionnés sont exactement TP+FN dans B0 et A1. L'inventaire par image, y compris surfaces natives et redimensionnées, est dans `mask_audit.csv`.",
    "## Bootstrap apparié descriptif post-hoc",
    f"{REPLICATES} réplications, seed {SEED}, NumPy `default_rng` (PCG64). Tirage avec remise **des images**, stratifié par catégorie et label normal/anormal : effectifs et prévalence sont conservés. Les mêmes indices sont utilisés pour B0 et A1, pour toutes les métriques. Les seuils et checkpoints restent fixes ; aucune recalibration dans une réplication. Dice/IoU agrègent les TP/FP/FN des images tirées, normales comprises, puis calculent le ratio ; aucun pixel n'est traité comme une observation indépendante. La macro est recalculée dans chaque réplication comme moyenne des trois catégories fixes. IC percentiles 2,5–97,5 %, sans correction de multiplicité. Toutes les réplications ont les deux classes et des dénominateurs non nuls.",
    "Ces IC sont conditionnels aux modèles entraînés, aux catégories et à la prévalence observée ; ils ne couvrent ni variabilité d'entraînement, ni choix du checkpoint, ni incertitude de calibration, ni nouveaux sites/catégories. Ils supposent les images échangeables dans chaque strate et ignorent d'éventuels groupes de production inconnus. Un intervalle excluant zéro reste une indication descriptive post-hoc, sans test confirmatoire ni causalité.",
    table(["Catégorie", "Métrique", "B0 [IC 95 %]", "A1 [IC 95 %]", "Δ [IC 95 %]"], [[r["category"], r["metric"], *[f"{r[k]:.6f} [{r[k + '_low']:.6f} ; {r[k + '_high']:.6f}]" for k in ("B0", "A1", "delta")]] for r in bootstrap]),
    "## Conclusions et limites",
    "**Confirmé au protocole initial :** A1 améliore bottle en classement image, F1 et segmentation micro, mais la segmentation y reste faible (Dice 0,0940). Sur hazelnut, l'AUROC image progresse légèrement (0,9318 → 0,9375), tandis que le rappel au seuil val chute de 41/70 à 11/70 et le Dice de 0,5044 à 0,2648. Un bon classement ne garantit donc pas une bonne décision au seuil fixé. Sur leather, B0 classe toutes les 32 normales positives ; A1 en classe 29/32 positives et manque 24/92 anomalies contre 1/92 pour B0, avec dégradation AUROC/AP/F1 et Dice/IoU. Le F1 élevé de B0 leather doit se lire avec ce FPR de 100 % et la prévalence anormale élevée. A1 n'améliore pas uniformément B0 ; aucune supériorité générale n'est établie.",
    "**Interprétation post-hoc :** les distributions et sous-groupes localisent les modes d'échec aux seuils existants ; ils ne prouvent pas leur cause. Les écarts de scores entre normales val et test, notamment leather, sont compatibles avec un décalage de distribution sans en identifier l'origine. La validation a aussi servi à sélectionner les checkpoints, et n'est donc pas une validation indépendante de la calibration. Les IC par images décrivent seulement l'incertitude conditionnelle précisée ci-dessus. Aucun réglage correctif ni choix T0/T1/T2 n'est effectué à partir du test.",
    "## Reproduction, fichiers locaux et conservation",
    "Commande depuis la racine :\n\n```powershell\n& .venv/Scripts/python.exe scripts/diagnose_b0_a1.py\n```",
    "Le script ne charge aucun modèle et ne contient aucun appel d'inférence ou d'entraînement. Il s'arrête si une incohérence de données, provenance, seuil, métrique ou conservation est détectée. Les figures et tables exactes se trouvent dans le dossier **ignoré par Git** `reports/experiments/b0_a1_diagnostic_local/` : `confusion.png`, `score_distributions.png`, `roc.png`, `pr.png`, `confusion.csv`, `differences.csv`, `defect_metrics.csv`, `bootstrap.csv`, `mask_audit.csv`, `roc_points.csv`, `pr_points.csv`, `audit.json`, `preservation.json`. Les liens de figures fonctionnent dans la copie locale ; les PNG ignorés ne seront pas présents dans un clone Git seul.",
    f"Conservation vérifiée avant/après : **{len(conservation)} fichiers préexistants identiques par SHA256**, notamment les deux arbres officiels, le premier rapport de suivi et ses sources, les six checkpoints, configurations, sources et manifestes. L'inventaire détaillé est dans `preservation.json`. Aucun entraînement T0/T1/T2 n'a été lancé."
    ]
    return "\n\n".join(text) + "\n"


def main():
    torch.set_num_threads(2)
    require(not LOCAL.is_symlink() and not REPORT.is_symlink(), "Destination symbolique interdite")
    before = protected_inventory()
    reports, predictions, checks, masks = audit_inputs()
    print("Contrôles des six archives, images et masques réussis.", flush=True)
    bootstrap = paired_bootstrap(predictions)
    require(all(math.isfinite(r[k]) for r in bootstrap for k in ("B0_low", "A1_low", "delta_low", "B0_high", "A1_high", "delta_high")), "Bootstrap non défini")
    defects = defect_metrics(predictions)
    differences = []
    for category in (*CATEGORIES, "macro"):
        b, a = [np.mean([official_values(reports[m, c]) for c in CATEGORIES], axis=0) if category == "macro" else official_values(reports[m, category]) for m in MODELS]
        differences.extend({"category": category, "metric": name, "B0": float(b[i]), "A1": float(a[i]), "delta": float(a[i] - b[i])} for i, name in enumerate(ALL_NAMES))
    LOCAL.mkdir(parents=True, exist_ok=True)
    figures(predictions)
    for name, rows in (("bootstrap", bootstrap), ("defect_metrics", defects), ("differences", differences), ("mask_audit", masks), ("confusion", [{"category": c, "model": m.upper(), **confusion(predictions[m, c])} for c in CATEGORIES for m in MODELS])):
        write_csv(LOCAL / f"{name}.csv", rows)
    after = protected_inventory()
    require(before == after, "Fichier préexistant modifié pendant le diagnostic")
    write_json(LOCAL / "preservation.json", {"unchanged": True, "files": before})
    write_json(LOCAL / "audit.json", {"seed": SEED, "bootstrap_replicates": REPLICATES, "bootstrap_unit": "paired_image_stratified_category_label", "inference_executed": False, "training_executed": False, "calibration_executed": False, "checks_passed": True, "checks": checks, "source_hashes": before, "script_sha256": sha(Path(__file__)), "environment": {"python": platform.python_version(), **{p: version(p) for p in ("numpy", "scikit-learn", "matplotlib", "Pillow", "torch")}}, "empty_resized_anomalous_masks": [r["image_path"] for r in masks if r["label"] and not r["resized_positive_pixels"]], "limitations": ["pixel AUROC/AP copied from archived JSON; no continuous pixel scores", "pixel validation quantile not recomputed", "bootstrap conditional on fixed trained models and thresholds"]})
    REPORT.write_text(render_report(reports, predictions, checks, masks, bootstrap, defects, differences, before), encoding="utf-8")
    require(before == protected_inventory(), "Conservation finale échouée")
    print(json.dumps({"report": str(REPORT.relative_to(ROOT)), "preserved_files": len(before), "test_images": len(masks), "bootstrap_replicates": REPLICATES, "empty_masks": sum(r["label"] and r["resized_positive_pixels"] == 0 for r in masks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
