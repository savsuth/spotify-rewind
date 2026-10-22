"""Technical-log cross-check: matches existing plays and stays warning-free."""
import unittest
import warnings

from rewind import config, ingest, techlog


@unittest.skipUnless(config.EXPORT_DIR.exists() and (config.WORK_DIR / "metrics.json").exists(),
                     "needs the personal export and a full `python3 -m rewind build`")
class TechLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, _ = ingest.clean(ingest.load_export())

    def test_reconcile_runs_with_deprecations_as_errors(self):
        # A NumPy "generic unit" deprecation here would become a hard error in a
        # future NumPy release, so the check must not emit one.
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            result = techlog.reconcile_raw_core_stream(self.records)
        self.assertTrue(result["available"])
        self.assertEqual(result["log_events"], 7599)
        self.assertEqual(result["matched_events"] + result["unmatched_events"], result["log_events"])
        self.assertGreaterEqual(result["matched_events"] / result["log_events"], 0.99)


if __name__ == "__main__":
    unittest.main()
