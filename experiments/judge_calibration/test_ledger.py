from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.judge_calibration import ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "ledger.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_created_with_allocations_and_zero_usage(self):
        usage = ledger.usage(self.path)
        self.assertEqual({k: r["cap"] for k, r in usage.items()}, ledger.ALLOCATIONS)
        self.assertTrue(all(r["used"] == 0 for r in usage.values()))
        self.assertEqual(json.loads(self.path.read_text())["entries"], [])

    def test_reserve_and_cap(self):
        for n in range(10):
            entry = ledger.reserve("smoke", "run-a", path=self.path, note=f"job{n}")
            self.assertEqual(entry["seq"], n + 1)
        with self.assertRaises(ledger.BudgetExhausted):
            ledger.reserve("smoke", "run-a", path=self.path)
        self.assertEqual(ledger.usage(self.path)["smoke"], {"cap": 10, "used": 10, "remaining": 0})
        ledger.reserve("petri", "run-b", n=ledger.ALLOCATIONS["petri"], path=self.path)
        with self.assertRaises(ledger.BudgetExhausted):
            ledger.reserve("petri", "run-b", path=self.path)
        with self.assertRaises(ValueError):
            ledger.reserve("nope", "run-b", path=self.path)
        with self.assertRaises(ValueError):
            ledger.reserve("baseline", "run-b", n=0, path=self.path)
        self.assertIn("smoke            10   10          0", ledger.status_text(self.path))

    def test_concurrent_reservations_never_exceed_cap(self):
        def attempt(i):
            try:
                return ledger.reserve("smoke", f"t{i}", path=self.path)["seq"]
            except ledger.BudgetExhausted:
                return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(attempt, range(40)))
        granted = [r for r in results if r is not None]
        self.assertEqual(len(granted), 10)
        self.assertEqual(sorted(granted), list(range(1, 11)))
        data = json.loads(self.path.read_text())
        self.assertEqual(sum(e["n"] for e in data["entries"]), 10)


if __name__ == "__main__":
    unittest.main()
