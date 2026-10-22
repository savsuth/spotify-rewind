"""Synthetic exports: schema realism, and end-to-end recovery of planted ground truth."""
import json
from pathlib import Path
import tempfile
import unittest

from rewind import ingest, synth
from rewind.__main__ import main, parse_tz


class SyntheticExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.truth = synth.generate(cls.root / "export", seed=3, months=30)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_files_follow_the_real_export_schema_and_naming(self):
        files = sorted((self.root / "export").glob("Streaming_History_*.json"))
        self.assertTrue(any("_Audio_" in f.name for f in files))
        self.assertTrue(any("_Video_" in f.name for f in files))
        total = 0
        for f in files:
            for rec in json.loads(f.read_text()):
                total += 1
                self.assertEqual(set(rec), set(ingest.EXPORT_FIELDS))
                self.assertRegex(rec["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
                self.assertTrue(rec["ip_addr"].startswith("192.0.2."))  # documentation range only
        self.assertEqual(total, self.truth["raw_records"])

    def test_planted_eras_fit_inside_the_export(self):
        self.assertEqual(len(self.truth["era_boundaries"]), 4)
        self.assertLess(max(self.truth["era_boundaries"]), "2024-09")  # 30 months from 2022-03

    def test_never_overwrites_a_real_export(self):
        real = self.root / "real_export"
        real.mkdir()
        (real / "Streaming_History_Audio_2024.json").write_text("[]")
        with self.assertRaises(FileExistsError):
            synth.generate(real, seed=1, months=24)
        self.assertTrue((real / "Streaming_History_Audio_2024.json").exists())

    def test_regenerating_into_its_own_folder_is_allowed(self):
        again = synth.generate(self.root / "export", seed=3, months=30)
        self.assertEqual(again["raw_records"], self.truth["raw_records"])

    def test_short_exports_are_rejected(self):
        with self.assertRaises(ValueError):
            synth.generate(self.root / "short", months=12)


class EndToEndTests(unittest.TestCase):
    def test_demo_recovers_every_planted_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["demo", "--out", tmp, "--seed", "11", "--quick"])
            report = json.loads((Path(tmp) / "outputs" / "evaluation.json").read_text())
            failed = [c for c in report["checks"] if not c["pass"]]
            self.assertEqual(failed, [])
            self.assertEqual(code, 0)
            site = Path(tmp) / "site"
            for name in ("index.html", "styles.css", "js/app.js", "data/stories.json"):
                self.assertTrue((site / name).exists(), name)
            self.assertTrue(list((site / "data" / "charts").glob("clock-all.svg")))

    def test_timezone_override_parsing(self):
        self.assertEqual(parse_tz(["us=America/Chicago", "IN=Asia/Kolkata"]),
                         {"US": "America/Chicago", "IN": "Asia/Kolkata"})
        with self.assertRaises(SystemExit):
            parse_tz(["America/Chicago"])

    def test_timezone_override_changes_local_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            synth.generate(Path(tmp) / "export", seed=5, months=24)
            raw = ingest.load_export(Path(tmp) / "export")
            east, _ = ingest.clean(raw)
            central, audit = ingest.clean(raw, {"US": "America/Chicago"})
            self.assertEqual(audit["timezone_map"]["US"], "America/Chicago")
            us = raw["conn_country"].to_numpy() == "US"
            shift = (east["local_ts"] - central["local_ts"])[us].dt.total_seconds()
            # One hour apart, except in the hour around a daylight-saving switch, when the
            # zones (which change at the same local time) are briefly 0 or 2 hours apart.
            self.assertTrue(set(shift.unique()) <= {0.0, 3600.0, 7200.0})
            self.assertGreater((shift == 3600.0).mean(), 0.99)


if __name__ == "__main__":
    unittest.main()
