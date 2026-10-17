import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Text(unittest.TestCase):
    """scrub, environment, issue_text: what reaches GitHub."""


class Gh(unittest.TestCase):
    """gh_status, open_matches, post, record_issue against a fake gh on PATH."""


class FileCommand(unittest.TestCase):
    """cmd_tool_bug: post on the maintainer's machine or with --approved, else save a draft; search before every create."""


class Cli(unittest.TestCase):
    """`compose tool-bug` and `compose toolsmith` through the real entry point."""
