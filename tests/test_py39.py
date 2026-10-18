import hermetic  # first: no test sees the real home
import ast
import os
import unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""

ROOT = Path(__file__).resolve().parents[1]


def newer_than_3_9(path):
    """`file:line name` for each use of a stdlib API that the Python 3.9 macOS ships lacks; a 3.10+ syntax error raises."""
    tree = ast.parse(path.read_text(), str(path), feature_version=(3, 9))
    rel = path.relative_to(ROOT)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr == "enterContext":
            out.append(f"{rel}:{n.lineno} TestCase.enterContext (3.11)")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "zip" and any(k.arg == "strict" for k in n.keywords):
            out.append(f"{rel}:{n.lineno} zip(strict=) (3.10)")
    return out


class Python39(unittest.TestCase):
    def test_cli_and_its_tests_run_on_the_python_macos_ships(self):
        files = sorted((ROOT / "bin").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
        self.assertEqual([hit for f in files for hit in newer_than_3_9(f)], [])


if __name__ == "__main__":
    unittest.main()
