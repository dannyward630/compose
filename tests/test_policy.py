import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, sys, unittest
from pathlib import Path
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_policy  # noqa: E402

DOC = """# Verification policies
Intro text.
## Auth
Auth changes need a security review.
Keys too.
globs: bin/auth*.py, bin/keys/*
checks: security review, auth tests
## Migrations
A change to stored data runs a dry run first.
checks: migration dry run
"""
AUTH = {"name": "Auth", "statement": "Auth changes need a security review. Keys too.", "globs": ["bin/auth*.py", "bin/keys/*"], "checks": ["security review", "auth tests"]}
MIGRATIONS = {"name": "Migrations", "statement": "A change to stored data runs a dry run first.", "globs": [], "checks": ["migration dry run"]}


class Parse(unittest.TestCase):
    def test_brief_example(self):
        self.assertEqual(fc_policy.parse_policies(DOC), [AUTH, MIGRATIONS])

    def test_holdout_spacing_empty_parts_and_preamble(self):
        text = "globs: *\nchecks: early\n##   Spaced name  \n\n   first line   \n\t\n  globs: a/*, , b ,\n### not a heading\n  checks:  ,x,\n## Empty\n"
        self.assertEqual(fc_policy.parse_policies(text), [
            {"name": "Spaced name", "statement": "first line ### not a heading", "globs": ["a/*", "b"], "checks": ["x"]},
            {"name": "Empty", "statement": "", "globs": [], "checks": []}])
        self.assertEqual(fc_policy.parse_policies("# Title\nno policies here\n"), [])

    def test_glob_matches(self):
        policies = [AUTH, MIGRATIONS]
        self.assertEqual(fc_policy.glob_matches(policies, ["bin/auth_keys.py"]), [AUTH])
        self.assertEqual(fc_policy.glob_matches(policies, ["bin/keys/deep/k.pem"]), [AUTH])
        self.assertEqual(fc_policy.glob_matches(policies, ["bin/other.py", "migrations/1.sql"]), [])
        self.assertEqual(fc_policy.glob_matches(policies, []), [])

    def test_holdout_once_each_in_document_order(self):
        a = {"name": "A", "statement": "", "globs": ["x/*", "*.md"], "checks": []}
        b = {"name": "B", "statement": "", "globs": ["y/*"], "checks": []}
        plain = {"name": "P", "statement": "", "globs": [], "checks": ["c"]}
        files = ["y/1.py", "x/2.py", "x/README.md"]
        self.assertEqual(fc_policy.glob_matches([a, plain, b], files), [a, b])


if __name__ == "__main__":
    unittest.main()
