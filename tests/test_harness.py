import hermetic  # first: no test sees the real home
import contextlib, io, os, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_checks, fc_harness, fc_init, fc_links, fc_steprun, fc_steps


class CodexSkillLink(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co = tmp / "bin", tmp / "home", tmp / "co"
        for d in (self.bin, self.home, self.co): d.mkdir()
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)
        h = self.home
        self.three = [("compose CLI link", h / ".local/bin/compose", self.co / "bin/compose"),
                      ("compose skill link", h / ".claude/skills/compose", self.co), ("bp link", h / ".local/bin/bp", self.co / "bp/bin/bp.mjs")]

    def codex(self):
        (self.bin / "codex").write_text("#!/bin/sh\n"); (self.bin / "codex").chmod(stat.S_IRWXU)

    def second(self):
        (self.bin / "other").write_text("#!/bin/sh\n"); (self.bin / "other").chmod(stat.S_IRWXU)
        row = {**fc_harness.HARNESSES.get("codex", {}), "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}
        p = mock.patch.dict(fc_harness.HARNESSES, {"other": row}); p.start(); self.addCleanup(p.stop)

    def test_codex_on_path_adds_its_skill_link_after_the_three(self):
        self.codex()
        self.assertEqual(fc_checks.owned_links(self.co), self.three + [("Codex skill link", self.home / ".codex/skills/compose", self.co)])
        os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        self.assertEqual(fc_checks.owned_links(self.co)[3:], [("Codex skill link", self.home / "elsewhere/skills/compose", self.co)])

    def test_no_codex_is_exactly_the_three_links(self):
        self.assertEqual(fc_checks.owned_links(self.co), self.three)
        os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        self.assertEqual(fc_checks.owned_links(self.co), self.three)

    def test_a_second_installed_row_follows_codex_under_its_own_skills_dir(self):
        self.codex(); self.second()
        other = ("Other skill link", self.home / ".other/skills/compose", self.co)
        self.assertEqual(fc_checks.owned_links(self.co)[3:], [("Codex skill link", self.home / ".codex/skills/compose", self.co), other])
        (self.bin / "codex").unlink()
        self.assertEqual(fc_checks.owned_links(self.co)[3:], [other])

    def test_relink_links_the_skill_only_with_codex_on_path(self):
        os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        fc_links.relink_owned(self.co)
        self.assertFalse((self.home / ".codex").exists() or (self.home / "elsewhere").exists())
        self.codex(); fc_links.relink_owned(self.co)
        self.assertEqual((self.home / "elsewhere/skills/compose").resolve(), self.co.resolve())


class CodexSkillRow(unittest.TestCase):
    NAME = "Codex skill link"
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co = tmp / "bin", tmp / "home", tmp / "co"
        for d in (self.bin, self.home, self.co / "bin"): d.mkdir(parents=True)
        for f in ("bin/compose.py", "SKILL.md"): (self.co / f).write_text("")  # a compose checkout
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)
        self.link = self.home / ".codex/skills/compose"
        names = [r[0] for r in fc_steps.STEPS]
        self.row = fc_steps.STEPS[names.index(self.NAME)]
        self.assertEqual(names[names.index(self.NAME) - 1], "compose skill link")

    def codex(self):
        (self.bin / "codex").write_text("#!/bin/sh\n"); (self.bin / "codex").chmod(stat.S_IRWXU)

    def run_row(self, dry=False): return fc_steprun.run_step(self.row, self.co, True, False, False, dry=dry)

    def test_row_is_an_optional_default_write_row(self):
        self.assertEqual(self.row[2:], ("compose setup", "default", False, "write"))
        self.assertEqual(set(fc_steprun.WRITERS), set(fc_steprun.PREVIEWS))

    def test_without_codex_the_check_passes_and_run_step_does_nothing(self):
        self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))
        self.assertEqual(self.run_row(), ("ok", ""))

    def test_with_codex_the_check_reads_like_the_compose_skill_link(self):
        self.codex()
        self.assertEqual(fc_steps.check(self.row, self.co), (False, "~/.codex/skills/compose is missing"))
        self.link.parent.mkdir(parents=True); self.link.symlink_to(self.home / "gone")
        self.assertEqual(fc_steps.check(self.row, self.co), (False, f"dangling link {self.link} -> {self.home / 'gone'}"))
        self.link.unlink(); self.link.symlink_to(self.co)
        self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))

    def test_run_step_links_the_checkout_then_a_second_run_finds_it_ok(self):
        self.codex()
        self.assertEqual(self.run_row()[0], "done")
        self.assertEqual(self.link.resolve(), self.co.resolve())
        self.assertEqual(self.run_row(), ("ok", ""))

    def test_dry_run_previews_and_writes_nothing(self):
        self.codex()
        self.assertEqual(self.run_row(dry=True), ("would", f"would link ~/.codex/skills/compose -> {self.co}"))
        self.assertFalse(self.link.exists())

    def test_codex_home_moves_the_link(self):
        self.codex(); os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        self.assertEqual(self.run_row()[0], "done")
        self.assertEqual((self.home / "elsewhere/skills/compose").resolve(), self.co.resolve())

    def test_doctor_lists_the_missing_link_as_optional(self):
        self.codex(); out = io.StringIO()
        with contextlib.redirect_stdout(out): fc_init.check_deps()
        self.assertIn("MISSING: Codex skill link: ~/.codex/skills/compose is missing (install: compose setup) - optional\n", out.getvalue())


class CodexCommands(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co = tmp / "bin", tmp / "home", tmp / "co"
        for d in (self.bin, self.home, self.co / "commands"): d.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)
        for n in ("yolo", "planner"): (self.co / f"commands/{n}.md").write_bytes(f"# {n}\r\nRun $ARGUMENTS \xe9\n".encode())
        (self.co / "commands/notes.txt").write_text("not a command")
        s = self.home / ".codex/skills"
        self.planner, self.yolo = s / "compose-planner/SKILL.md", s / "compose-yolo/SKILL.md"

    def tool(self, name="codex"):
        (self.bin / name).write_text("#!/bin/sh\n"); (self.bin / name).chmod(stat.S_IRWXU)

    def test_without_the_exe_nothing_is_listed_checked_or_created(self):
        self.assertEqual(fc_checks.command_copies("codex", self.co), [])
        self.assertEqual(fc_checks.commands_ok("codex", self.co), (True, ""))
        fc_links.relink_owned(self.co)
        self.assertFalse((self.home / ".codex").exists())

    def test_one_copy_per_command_sorted_by_name(self):
        self.tool()
        self.assertEqual(fc_checks.command_copies("codex", self.co), [(self.planner, self.co / "commands/planner.md"), (self.yolo, self.co / "commands/yolo.md")])

    def test_check_names_the_first_missing_or_stale_copy(self):
        self.tool()
        self.assertEqual(fc_checks.commands_ok("codex", self.co), (False, "~/.codex/skills/compose-planner/SKILL.md is missing"))
        fc_links.write_commands("codex", self.co)
        self.assertEqual(fc_checks.commands_ok("codex", self.co), (True, ""))
        self.yolo.write_bytes(b"old")
        self.assertEqual(fc_checks.commands_ok("codex", self.co), (False, "~/.codex/skills/compose-yolo/SKILL.md is stale"))

    def test_write_copies_bytes_replaces_stale_then_a_second_write_changes_nothing(self):
        self.tool(); self.yolo.parent.mkdir(parents=True); self.yolo.write_bytes(b"old")
        self.assertEqual(fc_links.write_commands("codex", self.co), [f"wrote {self.planner}", f"wrote {self.yolo}"])
        for copy, name in ((self.planner, "planner"), (self.yolo, "yolo")): self.assertEqual(copy.read_bytes(), (self.co / f"commands/{name}.md").read_bytes())
        self.assertEqual(fc_links.write_commands("codex", self.co), [f"ok {self.planner}", f"ok {self.yolo}"])

    def test_a_symlink_or_directory_is_refused_untouched(self):
        self.tool(); other = self.home / "other.md"; other.write_bytes(b"mine")
        self.planner.parent.mkdir(parents=True); self.planner.symlink_to(other)
        self.yolo.mkdir(parents=True)
        lines = fc_links.write_commands("codex", self.co)
        self.assertTrue(lines[0].startswith(f"refused {self.planner}: ") and lines[1].startswith(f"refused {self.yolo}: "))
        self.assertEqual((os.readlink(self.planner), other.read_bytes()), (str(other), b"mine"))
        self.assertTrue(self.yolo.is_dir() and not any(self.yolo.iterdir()))

    def test_relink_ends_with_one_commands_line_per_copy(self):
        self.tool()
        self.assertEqual(fc_links.relink_owned(self.co)[-2:], [f"Codex commands: wrote {self.planner}", f"Codex commands: wrote {self.yolo}"])
        self.assertEqual(fc_links.relink_owned(self.co)[-2:], [f"Codex commands: ok {self.planner}", f"Codex commands: ok {self.yolo}"])

    def test_another_row_gets_its_own_copies_under_its_skills_dir(self):
        self.tool("other")
        row = {**fc_harness.HARNESSES.get("codex", {}), "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}
        with mock.patch.dict(fc_harness.HARNESSES, {"other": row}):
            copy = self.home / ".other/skills/compose-yolo/SKILL.md"
            self.assertEqual(fc_checks.command_copies("other", self.co)[1], (copy, self.co / "commands/yolo.md"))
            self.assertEqual(fc_links.write_commands("other", self.co)[1], f"wrote {copy}")
            self.assertIn(f"Other commands: ok {copy}", fc_links.relink_owned(self.co))
        self.assertFalse((self.home / ".codex").exists())
