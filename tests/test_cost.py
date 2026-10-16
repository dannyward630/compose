import importlib.machinery, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import fc_cost, fc_sessions  # noqa: E402

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(BIN / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


if __name__ == "__main__":
    unittest.main()
