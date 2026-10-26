import hermetic  # first: no test sees the real home
import ast
import io
import os
import tokenize
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
    out += quote_reuse(path.read_text(), rel)
    return out


def quote_reuse(source, rel):
    """`file:line` for a string inside an f-string that reuses the f-string's own quote: valid only on 3.12+ (PEP 701), which
    `ast.parse(feature_version=)` does not reject. Needs the 3.12 tokenizer (FSTRING_START); on older ones such code cannot even parse."""
    start = getattr(tokenize, "FSTRING_START", None)
    if start is None:
        return []
    out, open_quotes = [], []
    for t in tokenize.generate_tokens(io.StringIO(source).readline):
        if t.type in (start, tokenize.STRING):
            quote = t.string.lstrip("rRbBfFuU")
            if open_quotes and quote[:len(open_quotes[-1])] == open_quotes[-1]:
                out.append(f"{rel}:{t.start[0]} quote reused inside an f-string (3.12)")
            if t.type == start:
                open_quotes.append(quote)
        elif t.type == tokenize.FSTRING_END:
            open_quotes.pop()
    return out


class Python39(unittest.TestCase):
    def test_cli_and_its_tests_run_on_the_python_macos_ships(self):
        files = sorted((ROOT / "bin").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
        self.assertEqual([hit for f in files for hit in newer_than_3_9(f)], [])


if __name__ == "__main__":
    unittest.main()
