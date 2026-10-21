import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Classify(unittest.TestCase):
    """A regression test's run on the base: a pass, a harness error, or a failure that proves it."""


class Prove(unittest.TestCase):
    """The regression test runs on the base and on the fix, and the proof says whether it proves the fix."""


class Record(unittest.TestCase):
    """A proof's red and final rows go on the task's ledger."""
