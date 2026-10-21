import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Pin(unittest.TestCase):
    """A proven regression test is pinned into the task's protected files and test command."""


class Regress(unittest.TestCase):
    """A FAST fix passes only after its regression test is proven and saved."""


class Reprove(unittest.TestCase):
    """A regression test that is not proof re-prompts its writer up to the attempts, then leaves the task unproven."""
