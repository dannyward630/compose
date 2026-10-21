import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import subprocess, sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_regproof  # noqa: E402


def proc(code, out="", err=""):
    return subprocess.CompletedProcess(["t"], code, out, err)


class Classify(unittest.TestCase):
    """A regression test's run on the base: a pass, a harness error, or a failure that proves it."""

    def test_pattern(self):
        self.assertEqual(fc_regproof.HARNESS_RE.pattern, r"ImportError|ModuleNotFoundError|Failed to import test module|ERROR collecting|errors? during collection")

    def test_exit_zero_passes_even_naming_an_import_error(self):
        for out in ("", "ImportError: x\nOK", "command not found"):
            self.assertEqual(fc_regproof.base_result(proc(0, out)), ("pass", False), out)

    def test_exit_124_is_an_error(self):
        self.assertEqual(fc_regproof.base_result(proc(124, "plain output")), ("error", None))

    def test_harness_output_is_an_error_in_stdout_or_stderr(self):
        for text in ("bash: pytest: command not found", "ImportError: no x", "ModuleNotFoundError: y", "Failed to import test module: t",
                     "ERROR collecting tests/t.py", "1 error during collection", "2 errors during collection"):
            for out, err in ((text, ""), ("", text)):
                self.assertEqual(fc_regproof.base_result(proc(1, out, err)), ("error", None), text)

    def test_other_failing_exit_fails_expected(self):
        for code in (1, 2, 5, -9):
            self.assertEqual(fc_regproof.base_result(proc(code, "AssertionError: 1 != 2")), ("fail_expected", True), code)

    def test_missing_output_is_handled(self):
        self.assertEqual(fc_regproof.base_result(proc(1, None, None)), ("fail_expected", True))
        self.assertEqual(fc_regproof.base_result(proc(0, None, None)), ("pass", False))
        self.assertEqual(fc_regproof.base_result(proc(1, None, "ImportError: x")), ("error", None))
        self.assertEqual(fc_regproof.base_result(proc(124, None, None)), ("error", None))


class Prove(unittest.TestCase):
    """The regression test runs on the base and on the fix, and the proof says whether it proves the fix."""


class Record(unittest.TestCase):
    """A proof's red and final rows go on the task's ledger."""
