import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
import sys
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "compose")
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(CLI).with_name("compose.py"))))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

CONV = {"types": ["feat", "fix", "chore", "test", "docs", "refactor", "build", "ci"], "example": "feat: add resume upload"}


class CommitConvention(unittest.TestCase):
    def test_task_commit_type_follows_what_the_task_changes(self):
        msg = lambda title, files: fc.fc_layers.commit_message({"title": title, "files": files}, CONV)
        self.assertEqual(msg("001 Save resumes", ["src/store.js"]), "feat: Save resumes")
        self.assertEqual(msg("002 Fix the empty upload", ["src/store.js"]), "fix: Fix the empty upload")
        self.assertEqual(msg("003 Add lodash", ["package.json", "package-lock.json"]), "chore: Add lodash")
        self.assertEqual(msg("004 Explain setup", ["README.md"]), "docs: Explain setup")

    def test_no_convention_keeps_plain_messages(self):
        self.assertEqual(fc.fc_layers.commit_message({"title": "001 Save resumes", "files": ["a.js"]}), "Save resumes")
        self.assertEqual(fc.fc_verify.fix_message("Save in one transaction", ["a.js"]), "Save in one transaction")

    def test_fix_message_drops_lines_about_the_tool_but_keeps_compose_files(self):
        self.assertEqual(fc.fc_verify.fix_message("Ran compose verify", ["a.js"]), "Fix a.js")
        self.assertEqual(fc.fc_verify.fix_message("Fix docker-compose healthcheck", ["a.yml"]), "Fix docker-compose healthcheck")
        self.assertEqual(fc.fc_verify.fix_message("Update compose.yaml port", ["compose.yaml"]), "Update compose.yaml port")
        self.assertEqual(fc.fc_verify.fix_message("Pin composer version", ["composer.json"]), "Pin composer version")

    def test_fix_loop_commit_is_a_fix_and_unlisted_types_fall_back(self):
        self.assertEqual(fc.fc_verify.fix_message("Save in one transaction", ["a.js"], CONV), "fix: Save in one transaction")
        self.assertEqual(fc.fc_core.typed("Add lodash", "deps", {"types": ["feat", "build"]}), "build: Add lodash")
        self.assertEqual(fc.fc_core.typed("Add lodash", "deps", {"types": ["feat"]}), "Add lodash")

    def test_message_problem_names_the_process_and_leaves_plain_words_alone(self):
        bad = fc.fc_layers.message_problem
        for m in ("Add search (task 004)", "Wire compose verify into CI", "Land wave 2 of the work", "Fix what the teammate broke", "Close the Linear issue first",
                  "Add search\n\nCo-authored-by: A <a@b.c>", "001: Add search", "", "compose's retry loop", "Apply the fix round result"):
            self.assertTrue(bad(m), m)
        for m in ("Add search", "Pin composer version", "Fix docker-compose healthcheck", "Update compose.yaml port", "Add a wavelength slider"):
            self.assertEqual(bad(m), "", m)
        self.assertIn("no type prefix", bad("Add search", CONV))
        self.assertEqual(bad("feat(api)!: add search", CONV), "")

    def test_a_task_title_that_names_the_process_gives_update_files_in_the_commit(self):
        msg = lambda title, files, conv=None: fc.fc_layers.commit_message({"title": title, "files": files}, conv)
        self.assertEqual(msg("Task 001", ["src/a.js", "src/b.js"]), "Update src/a.js, src/b.js")
        self.assertEqual(msg("Wire compose run into CI", ["ci.yml"], CONV), "chore: Update ci.yml")
        self.assertEqual(msg("Cover the toggle", ["tests/toggle.test.js"], CONV), "test: Cover the toggle")

    def test_a_task_title_with_a_role_word_still_names_the_change(self):
        msg = lambda title, files: fc.fc_layers.commit_message({"title": title, "files": files})
        self.assertEqual(msg("herdr implementer runs a local model in pi", ["bin/fc_implement.py"]), "herdr implementer runs a local model in pi")
        self.assertEqual(msg("Setup probes a local implementer without an OpenRouter key", ["bin/fc_defaults.py"]), "Setup probes a local implementer without an OpenRouter key")
        self.assertEqual(msg("Show the team lead which teammates are idle", ["a.py"]), "Show the team lead which teammates are idle")

    def test_scrub_message_keeps_what_describes_the_change_and_drops_the_process(self):
        scrub = fc.fc_layers.scrub_message
        self.assertEqual(scrub("task 001: add search\n\nDone by the implementer.\nIndex the title.", ["a.js"]), "add search\n\nIndex the title.")
        self.assertEqual(scrub("Wave 2 groundwork for compose run", ["src/a.js"]), "Update a.js")
        self.assertEqual(scrub("tests for task 003", ["tests/a.test.js", "tests/b.test.js"]), "Add tests in a.test.js, b.test.js")
        self.assertEqual(scrub("Add search", ["a.js"], CONV), "feat: Add search")
        self.assertEqual(scrub("Add search", ["a.js"]), "Add search")

    def test_briefs_carry_the_convention_and_forbid_config_tests(self):
        meta = {"id": "001", "protected": ["tests/a.test.js"], "test": "true"}
        plain, typed = fc.fc_briefs.test_brief(meta, ""), fc.fc_briefs.test_brief(meta, "", conv=CONV)
        self.assertIn("<plain message>", plain)
        self.assertIn("test: ", typed)
        self.assertNotIn("<plain message>", typed)
        for brief in (plain, typed):
            self.assertIn("dependency lists", brief)
        d = Path(tempfile.mkdtemp())
        (d / "verify.json").write_text(json.dumps({"commit_convention": CONV}))
        self.assertEqual(fc.fc_core.commit_convention(d), CONV)
        self.assertIn("feat: add resume upload", fc.fc_crew.crew_preamble(d, "p-x", "t"))
        self.assertNotIn("type prefix", fc.fc_crew.crew_preamble(Path(tempfile.mkdtemp()), "p-x", "t"))


if __name__ == "__main__":
    unittest.main()
