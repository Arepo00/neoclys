import json
import os
import tempfile
import unittest

from neocly_os import NeoclyOS, run_verification


class NeoclyOSTest(unittest.TestCase):
    def test_full_cycle_generates_metrics_and_actions(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.db")
            sys = NeoclyOS(db_path=db, seed=7)
            sys.init_db()
            inserted = sys.seed_leads(3000)
            self.assertGreater(inserted, 0)

            results = sys.run_days(60)
            self.assertEqual(len(results), 60)

            report = sys.report()
            self.assertGreater(report["outreaches"], 0)
            self.assertGreater(report["qualified_bookings"], 0)
            self.assertGreater(report["f2a_actions"], 0)
            self.assertGreaterEqual(report["avg_qualified_calls_per_day"], 2.0)
            self.assertIn("top_template", report)
            self.assertIn("top_playbook", report)
            json.dumps(report)

    def test_checkbox_verification_contract(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "verify.db")
            data = run_verification(db, seed=19)
            self.assertTrue(data["all_pass"])
            self.assertTrue(all(data["checks"].values()))


if __name__ == "__main__":
    unittest.main()
