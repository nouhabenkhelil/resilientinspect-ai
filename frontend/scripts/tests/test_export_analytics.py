"""Scientific public-export regression checks; no inference or image access."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("export_analytics", ROOT / "frontend/scripts/export-analytics.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = exporter.build(ROOT)

    def test_fifteen_unique_records_and_confusion_coverage(self):
        records = self.export["records"]
        self.assertEqual(len(records), 15)
        self.assertEqual(len({(r["model"], r["category"]) for r in records}), 15)
        for record in records:
            self.assertEqual(sum(record["confusion"].values()), record["images"])
            self.assertEqual(record["pixel"] is None, record["model"].startswith("T"))
            official = json.loads((ROOT / record["source"]).read_text())
            self.assertEqual(record["threshold"], official["image_threshold"])

    def test_autoencoder_macro_matches_official_archives(self):
        for variant in ("B0", "A1"):
            source = ROOT / f"reports/evaluation/{variant.lower()}/f515662ab4ef/macro_metrics.json"
            official = json.loads(source.read_text())
            actual = next(r for r in self.export["macro"] if r["model"] == variant)
            for key in ("auroc", "ap", "f1"):
                self.assertAlmostEqual(actual["image"][key], official[f"image_{key}"]["mean"], places=14)

    def test_public_export_excludes_raw_records_and_machine_paths(self):
        raw = json.dumps(self.export)
        for forbidden in ("image_path", "sample_id", "C:\\", "/kaggle/", "base64", "best.pt", ".png"):
            self.assertNotIn(forbidden, raw)
        for source in self.export["sources"]:
            self.assertEqual(source["sha256"], exporter.digest(ROOT / source["path"]))

    def test_ties_use_half_pair_credit_and_fixed_threshold(self):
        rows = [{"split": "val", "label": label, "score": score}
                for label, score in ((0, .2), (1, .8), (1, .2), (0, .2))]
        metrics = exporter.synthetic_metrics(rows, .2)
        self.assertEqual(metrics["confusion"], {"tp": 1, "tn": 2, "fp": 0, "fn": 1})
        self.assertEqual(metrics["auroc"], .75)
        self.assertEqual(metrics["ap"], .75)


if __name__ == "__main__":
    unittest.main()
