import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", CLI))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

CONV = {"types": ["feat", "fix", "chore", "test", "docs", "refactor", "build", "ci"], "example": "feat: add resume upload"}


class CommitConvention(unittest.TestCase):
    def test_task_commit_type_follows_what_the_task_changes(self):
        msg = lambda title, files: fc.commit_message({"title": title, "files": files}, CONV)
        self.assertEqual(msg("001 Save resumes", ["src/store.js"]), "feat: Save resumes")
        self.assertEqual(msg("002 Fix the empty upload", ["src/store.js"]), "fix: Fix the empty upload")
        self.assertEqual(msg("003 Add lodash", ["package.json", "package-lock.json"]), "chore: Add lodash")
        self.assertEqual(msg("004 Explain setup", ["README.md"]), "docs: Explain setup")

    def test_no_convention_keeps_plain_messages(self):
        self.assertEqual(fc.commit_message({"title": "001 Save resumes", "files": ["a.js"]}), "Save resumes")
        self.assertEqual(fc.fix_message("Save in one transaction", ["a.js"]), "Save in one transaction")

    def test_fix_loop_commit_is_a_fix_and_unlisted_types_fall_back(self):
        self.assertEqual(fc.fix_message("Save in one transaction", ["a.js"], CONV), "fix: Save in one transaction")
        self.assertEqual(fc.typed("Add lodash", "deps", {"types": ["feat", "build"]}), "build: Add lodash")
        self.assertEqual(fc.typed("Add lodash", "deps", {"types": ["feat"]}), "Add lodash")

    def test_briefs_carry_the_convention_and_forbid_config_tests(self):
        meta = {"id": "001", "protected": ["tests/a.test.js"], "test": "true"}
        plain, typed = fc.test_brief(meta, ""), fc.test_brief(meta, "", conv=CONV)
        self.assertIn("<plain message>", plain)
        self.assertIn("test: ", typed)
        self.assertNotIn("<plain message>", typed)
        for brief in (plain, typed):
            self.assertIn("dependency lists", brief)
        d = Path(tempfile.mkdtemp())
        (d / "verify.json").write_text(json.dumps({"commit_convention": CONV}))
        self.assertEqual(fc.commit_convention(d), CONV)
        self.assertIn("feat: add resume upload", fc.crew_preamble(d, "p-x", "t"))
        self.assertNotIn("type prefix", fc.crew_preamble(Path(tempfile.mkdtemp()), "p-x", "t"))


if __name__ == "__main__":
    unittest.main()
