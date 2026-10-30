"""Run the JS data-contract regressions through the existing unittest CI."""
import shutil
import subprocess
import unittest
from pathlib import Path

class DashboardContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node.js required for browser data contracts')
    def test_contracts(self):
        result=subprocess.run(['node','--test','tests/master-brain-contract.test.cjs','tests/ft-recovery-filter.test.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
