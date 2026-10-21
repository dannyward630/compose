import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class RunHolds(unittest.TestCase):
    """run holds a FAST task with no expected behavior, and prints that an implement-then-test task runs as test-first."""


class FastAttempts(unittest.TestCase):
    """A FAST task needs a green base: its existing tests pass before the fix, and the fix ends unproven."""


class UnprovenLinear(unittest.TestCase):
    """An unproven task stays In Progress on Linear with its comment, and watch wakes on unproven and broken_base."""


class UnprovenRun(unittest.TestCase):
    """An unproven task's dependents wait, and its run events carry no red event."""


class UnprovenWhy(unittest.TestCase):
    """The unproven comment says why the regression test is not proof once the proof has run."""
