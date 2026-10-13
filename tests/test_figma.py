import importlib.machinery, importlib.util, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class FigmaCheck(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))

    def check(self, figma=None):
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("sys.stdout", out):
            fc.cmd_figma(SimpleNamespace(repo=".", project="p", action="check", figma=figma, only=None))
        return out.getvalue()

    def stored(self):
        return json.loads((self.proj / "linear.json").read_text())

    def test_figma_key_parses_urls_and_bare_keys(self):
        for text, key in (("https://www.figma.com/design/AbCdEf123456/Shop?node-id=1-2", "AbCdEf123456"),
                          ("https://www.figma.com/design/AbCdEf123456/branch/BrAnCh789012/Shop", "BrAnCh789012"),
                          ("https://figma.com/board/BoArD1234567/Flow", "BoArD1234567"),
                          ("https://www.figma.com/slides/SlIdEs123456", "SlIdEs123456"),
                          ("AbCdEf123456", "AbCdEf123456"),
                          ("junk", None), ("abc123456", None), ("a" * 41, None), ("AbCdEf-123456", None),
                          ("https://example.com/design/AbCdEf123456/Shop", None)):
            self.assertEqual(fc.figma_key(text), key, text)

    def test_store_figma_keeps_other_keys_and_creates_missing_file(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "OldKey123456", "x": 1}))
        fc.store_figma(self.proj, "NewKey123456")
        self.assertEqual(self.stored(), {"feature": "ENG-1", "figma": "NewKey123456", "x": 1})
        (self.proj / "linear.json").unlink()
        fc.store_figma(self.proj, "NewKey123456")
        self.assertEqual(self.stored(), {"figma": "NewKey123456"})

    def test_check_stores_a_url_then_shows_the_stored_key(self):
        out = self.check("https://www.figma.com/design/AbCdEf123456/Shop?node-id=1-2")
        self.assertEqual(self.stored(), {"feature": "ENG-1", "figma": "AbCdEf123456"})
        self.assertIn("figma file AbCdEf123456 stored in ", out)
        self.assertIn("linear.json; confirm access with whoami and get_metadata through the Figma MCP", out)
        self.assertIn("figma file AbCdEf123456 stored in ", self.check())

    def test_check_refuses_junk_and_a_missing_key(self):
        with self.assertRaises(SystemExit) as e:
            self.check("not a key")
        self.assertEqual(str(e.exception), "not a Figma file url or key: not a key")
        self.assertEqual(self.stored(), {"feature": "ENG-1"})
        with self.assertRaises(SystemExit) as e:
            self.check()
        self.assertEqual(str(e.exception), "no Figma file: fast-coding figma check --figma <url or key>")

    def test_help_lists_check_and_judge(self):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding"), "figma", "--help"], capture_output=True, text=True)
        self.assertIn("{check,judge}", r.stdout)


class FigmaJudge(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
