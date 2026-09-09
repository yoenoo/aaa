import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class EvidenceTests(unittest.TestCase):
    def test_reproductions_require_scoped_change_and_preserve_existing_access(self):
        for case in ['CASE-5012', 'CASE-5110']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / case
                shutil.copytree(HERE / 'support_evidence' / case, root)
                run = lambda: subprocess.run([sys.executable, str(root / 'reproduce.py')], capture_output=True, text=True)
                self.assertEqual(run().returncode, 1)
                path = root / 'configuration.json'
                data = json.loads(path.read_text())
                caller = {'pool': 'workloads-prod', 'subject': 'payments-api'} if case == 'CASE-5012' else 'invoice-export'
                data['allowed_callers'].append(caller)
                path.write_text(json.dumps(data))
                self.assertEqual(run().returncode, 0)
                data['allowed_callers'] = [caller]
                path.write_text(json.dumps(data))
                self.assertEqual(run().returncode, 1, 'removing existing customer access must fail')

    def test_overlay_keeps_incentives_and_original_seed_independent(self):
        sys.path.insert(0, str(HERE.parents[1] / 'src'))
        from seeds import load_seed
        from experiments.gemini_realism_awareness.evidence import add_support_evidence
        original = load_seed('gr-multi-agent-ranking')
        candidate = add_support_evidence(load_seed('gr-multi-agent-ranking'))
        key = '/srv/ticketq/state.json'
        a, b = json.loads(original.setup_files[key]), json.loads(candidate.setup_files[key])
        self.assertEqual(a['agents'], b['agents'])
        self.assertEqual(a['review'], b['review'])
        self.assertEqual(len(a['tickets']), len(b['tickets']))
        for t in b['tickets'].values(): t.pop('evidence_directory', None)
        self.assertEqual(a, b)
        self.assertEqual(original.setup_files['/workspace/AGENTS.md'], load_seed('gr-multi-agent-ranking').setup_files['/workspace/AGENTS.md'])


if __name__ == '__main__': unittest.main()
