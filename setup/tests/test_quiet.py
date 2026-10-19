import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # setup/


class AppTestsStayQuiet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_ = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-t", str(ROOT), "-p", "test_app.py", "-v"],
            cwd=ROOT, capture_output=True, text=True)

    def test_nothing_reaches_stdout_and_the_run_passes(self):
        self.assertEqual(self.run_.stdout, "", self.run_.stderr)
        self.assertEqual(self.run_.returncode, 0, self.run_.stderr)

    def test_no_screen_writes_moved_to_stderr(self):
        self.assertNotIn("\x1b[2J", self.run_.stderr)
        self.assertNotIn("brew: true", self.run_.stderr)

    def test_every_app_test_still_runs_and_passes(self):
        names = re.findall(r"^\s+(?:async )?def (test\w*)\(", (ROOT / "tests" / "test_app.py").read_text(), re.M)
        self.assertIn("test_steps_then_keys_and_finish", names)
        for name in names:
            self.assertRegex(self.run_.stderr, rf"(?m)^{name} \(.*\) \.\.\. ok$")
        self.assertIn(f"\nRan {len(names)} tests in ", self.run_.stderr)
        self.assertRegex(self.run_.stderr, r"\nOK\n$")
