import importlib.machinery, importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class FigmaCheck(unittest.TestCase):
    pass


class FigmaJudge(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
