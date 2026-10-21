import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class StackDepth(unittest.TestCase):
    """The stack's depth is its deepest code task's route depth."""


class DepthConfig(unittest.TestCase):
    """The verify settings at the stack's depth."""


class DepthEvents(unittest.TestCase):
    """The stages the depth skips go on the feature's ledger."""


class VerifyDepth(unittest.TestCase):
    """verify runs the stages of the stack's deepest task."""
