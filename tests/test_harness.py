import hermetic  # first: no test sees the real home
import contextlib, hashlib, importlib.machinery, importlib.util, io, json, os, stat, subprocess, sys, tempfile, time, tomllib, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_checks, fc_config, fc_harness, fc_init, fc_links, fc_models, fc_steprun, fc_steps
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fc)

FC_MODULES = {n: m for n, m in sys.modules.items() if n.startswith("fc_")}

def reload_steps():  # another test file may have dropped or replaced the fc_* modules in sys.modules; reload against the ones imported here
    with mock.patch.dict(sys.modules, FC_MODULES):
        for m in (fc_steps, fc_steprun): importlib.reload(m)


class CodexIds(unittest.TestCase):
    def test_probe_command(self):
        head, prompt = ["codex", "exec", "--ephemeral", "--skip-git-repo-check"], "Reply with exactly: ok"
        self.assertEqual(fc_harness.probe_command("codex:gpt-6-sol"), head + ["-m", "gpt-6-sol", prompt])
        self.assertEqual(fc_harness.probe_command("codex:a:b"), head + ["-m", "a:b", prompt])
        for model in ("codex", "codex:"): self.assertEqual(fc_harness.probe_command(model), head + [prompt])

    def test_probe_result(self):
        def result(code, out, err, model="codex:gpt-6-sol"): return fc_harness.probe_result(model, subprocess.CompletedProcess([], code, out, err))
        refused = 'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The \'x\' model is not supported."}}'
        self.assertEqual(result(0, "", "ERROR: noise"), (True, "answered"))
        self.assertEqual(result(0, "", "", "codex"), (True, "answered"))
        self.assertEqual(result(1, "", "warn\n" + refused + "\n"), (False, "The 'x' model is not supported."))
        self.assertEqual(result(1, "", "ERROR: unexpected status 401 Unauthorized: no key\n", "codex"), (False, "unexpected status 401 Unauthorized: no key"))
        self.assertEqual(result(1, "", "ERROR: first\nERROR: second\n"), (False, "first"))
        self.assertEqual(result(1, "out\n", "x ERROR: not first\nlast\n\n"), (False, "last"))
        self.assertEqual(result(1, "a\nb\n\n", " \n"), (False, "b"))
        self.assertEqual(result(3, "", ""), (False, "exit 3"))

    def test_calls_go_through_the_codex_row(self):
        probe, result, p = mock.Mock(return_value=["x"]), mock.Mock(return_value=(False, "y")), subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.dict(fc_harness.HARNESSES, {"codex": {**fc_harness.HARNESSES.get("codex", {}), "probe": probe, "result": result}}):
            self.assertEqual(fc_harness.probe_command("codex:gpt-6-sol"), ["x"])
            probe.assert_called_once_with("gpt-6-sol")
            fc_harness.probe_command("codex:")
            probe.assert_called_with(None)
            self.assertEqual(fc_harness.probe_result("codex:gpt-6-sol", p), (False, "y"))
            result.assert_called_once_with(p)


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
        os.environ.pop("CODEX_HOME", None); self.link = self.home / ".codex/skills/compose"
        names = [r[0] for r in fc_steps.STEPS]
        self.row = fc_steps.STEPS[names.index(self.NAME)]
        self.assertEqual(names[names.index(self.NAME) - 1], "compose skill link")

    def tool(self, name="codex"):
        (self.bin / name).write_text("#!/bin/sh\n"); (self.bin / name).chmod(stat.S_IRWXU)

    def run_row(self, row=None, dry=False): return fc_steprun.run_step(row or self.row, self.co, True, False, False, dry=dry)

    def test_without_codex_the_check_passes_and_run_step_does_nothing(self):
        self.assertEqual(self.row[2:], ("compose setup", "default", False, "write"))
        self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))
        self.assertEqual(self.run_row(), ("ok", ""))

    def test_with_codex_the_check_reads_like_the_compose_skill_link(self):
        self.tool()
        self.assertEqual(fc_steps.check(self.row, self.co), (False, "~/.codex/skills/compose is missing"))
        self.link.parent.mkdir(parents=True); self.link.symlink_to(self.home / "gone")
        self.assertEqual(fc_steps.check(self.row, self.co), (False, f"dangling link {self.link} -> {self.home / 'gone'}"))
        self.link.unlink(); self.link.symlink_to(self.co)
        self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))

    def test_run_step_links_the_checkout_under_the_skills_dir_then_finds_it_ok(self):
        self.tool(); os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        self.assertEqual(self.run_row()[0], "done")
        self.assertEqual((self.home / "elsewhere/skills/compose").resolve(), self.co.resolve())
        self.assertEqual(self.run_row(), ("ok", ""))

    def test_dry_run_previews_and_writes_nothing(self):
        self.tool()
        self.assertEqual(self.run_row(dry=True), ("would", f"would link ~/.codex/skills/compose -> {self.co}"))
        self.assertFalse(self.link.exists())

    def test_every_harness_row_gets_its_own_skill_link_row(self):
        self.tool(); self.tool("other")
        self.addCleanup(reload_steps)
        p = mock.patch.dict(fc_harness.HARNESSES, {"other": {**fc_harness.HARNESSES["codex"], "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}})
        p.start(); self.addCleanup(p.stop)
        reload_steps()
        names = [r[0] for r in fc_steps.STEPS]; i = names.index(self.NAME); j = names.index("Other skill link")
        self.assertEqual(names[i - 1:i + 2], ["compose skill link", self.NAME, "Codex commands"])
        self.assertGreater(j, i)
        self.assertEqual(self.run_row(fc_steps.STEPS[j])[0], "done")
        self.assertEqual((self.home / ".other/skills/compose").resolve(), self.co.resolve())
        self.assertFalse(self.link.exists())
        self.assertEqual(set(fc_steprun.WRITERS), set(fc_steprun.PREVIEWS))

    def test_doctor_lists_the_missing_link_as_optional(self):
        self.tool(); out = io.StringIO()
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


class CodexCommandsRow(unittest.TestCase):
    NAME = "Codex commands"
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co = tmp / "bin", tmp / "home", tmp / "co"
        for d in (self.bin, self.home, self.co / "commands"): d.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)
        for n in ("yolo", "planner"): (self.co / f"commands/{n}.md").write_bytes(f"# {n}\nRun $ARGUMENTS\n".encode())
        s = self.home / ".codex/skills"
        self.planner, self.yolo = s / "compose-planner/SKILL.md", s / "compose-yolo/SKILL.md"
        names = [r[0] for r in fc_steps.STEPS]
        self.row = fc_steps.STEPS[names.index(self.NAME)]
        self.assertEqual(names[names.index(self.NAME) - 1], "Codex skill link")

    def codex(self):
        (self.bin / "codex").write_text("#!/bin/sh\n"); (self.bin / "codex").chmod(stat.S_IRWXU)

    def run_row(self, dry=False): return fc_steprun.run_step(self.row, self.co, True, False, False, dry=dry)

    def test_without_codex_the_check_passes_and_run_step_does_nothing(self):
        self.assertEqual(self.row[2:], ("compose setup", "default", False, "write"))
        self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))
        self.assertEqual(self.run_row(), ("ok", ""))

    def test_a_missing_or_stale_copy_fails_the_check_and_run_step_writes_the_copies(self):
        self.codex()
        self.assertEqual(fc_steps.check(self.row, self.co), (False, "~/.codex/skills/compose-planner/SKILL.md is missing"))
        self.assertEqual(self.run_row()[0], "done")
        self.assertEqual(self.yolo.read_bytes(), (self.co / "commands/yolo.md").read_bytes())
        self.assertEqual(self.run_row(), ("ok", ""))
        self.yolo.write_bytes(b"old")
        self.assertEqual(fc_steps.check(self.row, self.co), (False, "~/.codex/skills/compose-yolo/SKILL.md is stale"))
        self.assertEqual(self.run_row()[0], "done")
        self.assertEqual(self.yolo.read_bytes(), (self.co / "commands/yolo.md").read_bytes())

    def test_dry_run_previews_one_line_per_copy_and_writes_nothing(self):
        self.codex()
        self.assertEqual(self.run_row(dry=True), ("would", "would write ~/.codex/skills/compose-planner/SKILL.md; would write ~/.codex/skills/compose-yolo/SKILL.md"))
        self.assertFalse((self.home / ".codex").exists())

    def test_every_harness_row_gets_its_own_commands_row_after_its_skill_link_row(self):
        (self.bin / "other").write_text("#!/bin/sh\n"); (self.bin / "other").chmod(stat.S_IRWXU)
        self.addCleanup(reload_steps)
        p = mock.patch.dict(fc_harness.HARNESSES, {"other": {**fc_harness.HARNESSES["codex"], "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}})
        p.start(); self.addCleanup(p.stop)
        reload_steps()
        names = [r[0] for r in fc_steps.STEPS]; i = names.index("Other commands")
        self.assertEqual(names[i - 1], "Other skill link")
        row = fc_steps.STEPS[i]; self.assertEqual(row[2:], ("compose setup", "default", False, "write"))
        self.assertEqual(fc_steprun.run_step(row, self.co, True, False, False)[0], "done")
        self.assertEqual((self.home / ".other/skills/compose-yolo/SKILL.md").read_bytes(), (self.co / "commands/yolo.md").read_bytes())
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(set(fc_steprun.WRITERS), set(fc_steprun.PREVIEWS))

    def test_doctor_lists_the_first_missing_copy_as_optional(self):
        self.codex(); out = io.StringIO()
        with contextlib.redirect_stdout(out): fc_init.check_deps()
        self.assertIn("MISSING: Codex commands: ~/.codex/skills/compose-away/SKILL.md is missing (install: compose setup) - optional\n", out.getvalue())


class HarnessBlock(unittest.TestCase):
    CODEX = {"models": {"crew": {"default": "codex:gpt-6"}}}
    CFG = {"models": {"implementer": "pi:top", "crew": {"default": "claude:sonnet", "planner": "claude:opus"}},
           "workspace": "work", "workspaces": {"work": {"models": {"implementer": "pi:work"}}}, "harnesses": {"codex": CODEX}}

    def setUp(self):
        for k in ("HARNESS", "DEFAULT_MODEL", "CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK", "WORKSPACE"):
            p = mock.patch.object(fc_config, k, getattr(fc_config, k)); p.start(); self.addCleanup(p.stop)

    def apply(self, cfg, harness=None, **env):
        fc_config.write_config(cfg)
        with mock.patch.dict(os.environ):
            for k in ("COMPOSE_HARNESS", "CLAUDECODE"): os.environ.pop(k, None)
            os.environ.update(env)
            return fc_config.apply_config(move=False, harness=harness)

    def exits(self, cfg, message, **kw):
        with self.assertRaises(SystemExit) as e: self.apply(cfg, **kw)
        self.assertEqual(str(e.exception), f"{fc_config.CONFIG_PATH}: {message}")

    def test_session_harness_precedence(self):
        with mock.patch.dict(os.environ, {"COMPOSE_HARNESS": "gemini", "CLAUDECODE": "1"}):
            self.assertEqual(fc_config.session_harness("codex"), "codex")
            self.assertEqual(fc_config.session_harness(), "gemini")
            del os.environ["COMPOSE_HARNESS"]
            self.assertEqual(fc_config.session_harness(), "claude")
            os.environ["CLAUDECODE"] = "0"
            self.assertIsNone(fc_config.session_harness())

    def test_block_replaces_crew_whole_over_the_workspace_merge(self):
        self.apply(self.CFG, "codex")
        self.assertEqual((fc_config.CREW_MODELS, fc_config.DEFAULT_MODEL, fc_config.HARNESS), ({"default": "codex:gpt-6"}, "pi:work", "codex"))
        st = fc_config.settings(self.CFG, "codex")[1]
        self.assertNotIn("harnesses", st)
        self.assertEqual(st["models"]["implementer"], "pi:work")

    def test_block_from_the_workspace_and_a_top_level_key(self):
        cfg = {**self.CFG, "harnesses": {}, "workspaces": {"work": {"harnesses": {"codex": {**self.CODEX, "parallel": 4}}}}}
        self.assertEqual(fc_config.settings(cfg, "codex")[1]["parallel"], 4)

    def test_config_without_harnesses_is_unchanged(self):
        cfg = {k: v for k, v in self.CFG.items() if k != "harnesses"}
        self.assertEqual(fc_config.settings(cfg, "claude"), fc_config.settings(cfg))
        with self.assertRaises(SystemExit) as e: fc_config.settings(cfg, "codex")
        self.assertEqual(str(e.exception), f'{fc_config.CONFIG_PATH}: no "harnesses.codex" block')
        self.exits(cfg, 'no "harnesses.codex" block', COMPOSE_HARNESS="codex")

    def test_a_block_without_default_exits_active_or_not(self):
        bad = {**self.CFG, "harnesses": {"codex": self.CODEX, "gemini": {"models": {"crew": {"planner": "x"}}}}}
        for kw in ({"harness": "codex"}, {}):
            self.exits(bad, 'harnesses.gemini.models.crew has no "default"', **kw)

    def test_a_harness_argument_without_a_block_exits(self):
        self.exits(self.CFG, 'no "harnesses.gemini" block', harness="gemini")


class ClaudeTopLevel(unittest.TestCase):
    CFG, setUp, apply, exits = HarnessBlock.CFG, HarnessBlock.setUp, HarnessBlock.apply, HarnessBlock.exits
    NO_BLOCK = 'no "harnesses.codex" block'

    def test_claude_code_needs_no_claude_block(self):
        self.apply(self.CFG, CLAUDECODE="1")
        self.assertEqual((fc_config.HARNESS, fc_config.CREW_MODELS, fc_config.DEFAULT_MODEL), ("claude", self.CFG["models"]["crew"], "pi:work"))
        self.assertEqual(fc_config.settings(self.CFG, "claude"), fc_config.settings(self.CFG))

    def test_a_harness_without_a_block_exits_with_or_without_a_map(self):
        for harnesses in ({}, {"gemini": HarnessBlock.CODEX}, None):
            cfg = {**self.CFG, "harnesses": harnesses}
            if harnesses is None: del cfg["harnesses"]
            with self.subTest(harnesses=harnesses):
                self.exits(cfg, self.NO_BLOCK, COMPOSE_HARNESS="codex")
                self.exits(cfg, self.NO_BLOCK, CLAUDECODE="1", COMPOSE_HARNESS="codex")

    def test_an_explicit_claude_block_merges_as_codexs_does(self):
        claude = {"models": {"crew": {"default": "claude:haiku"}}}
        self.apply({**self.CFG, "harnesses": {"claude": claude}}, CLAUDECODE="1")
        self.assertEqual((fc_config.CREW_MODELS, fc_config.DEFAULT_MODEL), ({"default": "claude:haiku"}, "pi:work"))

    def test_a_block_without_default_exits_when_claude_has_no_block(self):
        bad = {**self.CFG, "harnesses": {"gemini": {"models": {"crew": {"planner": "x"}}}}}
        self.exits(bad, 'harnesses.gemini.models.crew has no "default"', CLAUDECODE="1")

    def test_no_session_harness_gives_the_top_level_as_today(self):
        self.apply(self.CFG)
        self.assertEqual((fc_config.HARNESS, fc_config.CREW_MODELS, fc_config.DEFAULT_MODEL), (None, self.CFG["models"]["crew"], "pi:work"))
        self.assertEqual(fc_config.settings(self.CFG, None), fc_config.settings(self.CFG))


class HarnessPassDown(unittest.TestCase):
    BLOCK = lambda m, t: {"models": {"crew": {"default": m, "tests": t}}}
    CFG = {"models": {"crew": {"default": "claude:top", "tests": "claude:toptests"}},
           "harnesses": {"codex": BLOCK("claude:cdx", "claude:cdxtests"), "gemini": BLOCK("claude:gem", "claude:gemtests")}}

    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"; self.proj.mkdir(parents=True)
        for k in ("HARNESS", "DEFAULT_MODEL", "CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK", "WORKSPACE"):
            p = mock.patch.object(fc_config, k, getattr(fc_config, k)); p.start(); self.addCleanup(p.stop)

    def start(self, *flags, cfg=CFG, **env):
        """(calls herdr got, the tab's env, the model the teammate record names) for `crew start --role tests-001`."""
        fc_config.write_config(cfg); calls = []
        def herdr(*args, **kw):
            calls.append(args)
            return {"agent": {"agent_status": "working"}} if args[:2] == ("agent", "get") else {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}} if args[:2] == ("tab", "create") else {}
        with mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"}), mock.patch.object(sys, "argv", ["compose", "crew", "start", "--role", "tests-001", "--brief", "Write the test.", *flags]), \
                mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "herdr", herdr), mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")), \
                mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_herdr, "herdr_space", return_value="w9"), mock.patch.object(time, "sleep"), \
                mock.patch.object(fc.fc_herdr, "herdr_find_space", return_value="w9"), mock.patch.object(fc.fc_frame0, "frame0_register"), \
                mock.patch.object(fc.fc_claude, "claude_trusted", return_value=True), mock.patch("builtins.print"):
            for k in ("COMPOSE_HARNESS", "CLAUDECODE"): os.environ.pop(k, None)
            os.environ.update(env)
            try: fc.main()
            except SystemExit as e: self.exit = e
        tab = next((c for c in calls if c[:2] == ("tab", "create")), ())
        rec = next(fc.fc_crew.crew_dir(self.proj).glob("*.json"), None)
        return calls, [tab[i + 1] for i, v in enumerate(tab) if v == "--env"], rec and json.loads(rec.read_text())["model"]

    def test_the_flag_names_the_block_for_the_tab_and_the_model(self):
        _, envs, model = self.start("--harness", "codex")
        self.assertIn("COMPOSE_HARNESS=codex", envs)
        self.assertEqual(model, "claude:cdxtests")  # the role's own entry in the block, not just its default

    def test_the_env_does_the_same_and_the_flag_wins(self):
        _, envs, model = self.start(COMPOSE_HARNESS="codex")
        self.assertEqual((("COMPOSE_HARNESS=codex" in envs), model), (True, "claude:cdxtests"))
        _, envs, model = self.start("--harness", "codex", COMPOSE_HARNESS="gemini")
        self.assertEqual((("COMPOSE_HARNESS=codex" in envs), ("COMPOSE_HARNESS=gemini" in envs), model), (True, False, "claude:cdxtests"))

    def test_no_flag_and_no_env_leaves_the_tab_and_the_model_as_today(self):
        _, envs, model = self.start()
        self.assertEqual(([e for e in envs if e.startswith("COMPOSE_HARNESS")], model), ([], "claude:toptests"))

    def test_a_flag_without_its_block_exits_before_any_herdr_call(self):
        calls, _, _ = self.start("--harness", "codex", cfg={k: v for k, v in self.CFG.items() if k != "harnesses"})
        self.assertEqual((calls, hasattr(self, "exit")), ([], True))


class CodexProbe(unittest.TestCase):
    ID, REFUSED = "gpt-6-sol", 'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"m"}}\n'

    def setUp(self):
        self.calls = []
        for p in (mock.patch.object(fc_config, "PROBE_CACHE", Path(tempfile.mkdtemp()) / "probe.json"), mock.patch.object(fc_models.subprocess, "run", self.fake_run)):
            p.start(); self.addCleanup(p.stop)
        fc_models._PROBED.clear(); self.addCleanup(fc_models._PROBED.clear)

    def fake_run(self, argv, **kw):
        self.calls.append(argv)  # a model called "bad" is refused
        bad = "bad" in argv
        return subprocess.CompletedProcess(argv, int(bad), "", self.REFUSED if bad else "")

    def command(self, mid): return ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-m", mid, "Reply with exactly: ok"]

    def test_command_and_result_are_codexs(self):
        self.assertEqual(fc_models.probe_command(f"codex:{self.ID}"), self.command(self.ID))
        self.assertEqual(fc_models.probe_result(f"codex:{self.ID}", subprocess.CompletedProcess([], 0, "", "")), (True, "answered"))
        self.assertEqual(fc_models.probe_result("codex:bad", subprocess.CompletedProcess([], 1, "", self.REFUSED)), (False, "m"))

    def test_bare_codex_is_available_without_a_process_or_a_cache_read(self):
        with mock.patch.object(fc_config, "PROBE_CACHE") as cache:
            for model in ("codex", "codex:"): self.assertEqual(fc_models.model_available(model), (True, "Codex's default model"))
        self.assertEqual((self.calls, cache.mock_calls), ([], []))

    def test_an_id_is_probed_once_and_a_pass_is_cached_for_the_day(self):
        self.assertEqual(fc_models.model_available(f"codex:{self.ID}"), (True, "answered"))
        fc_models._PROBED.clear()  # a new process still finds the day's cache file
        self.assertEqual(fc_models.model_available(f"codex:{self.ID}"), (True, "answered"))
        self.assertEqual(self.calls, [self.command(self.ID)])

    def test_a_refusal_is_returned_and_probed_again(self):
        for _ in range(2): self.assertEqual(fc_models.model_available("codex:bad"), (False, "m"))
        self.assertEqual(self.calls, [self.command("bad")] * 2)

    def test_models_probe_lists_codex_entries_with_their_results(self):
        out = []
        with mock.patch.object(fc_config, "CREW_MODELS", {"a": f"codex:{self.ID}", "b": "codex:bad", "c": "codex"}), mock.patch.object(fc_config, "CREW_FALLBACK", {}), \
                mock.patch("builtins.print", lambda *a: out.append(" ".join(map(str, a)))):
            fc_models.cmd_models(SimpleNamespace(probe=True))
        self.assertEqual(out, [f"codex:{self.ID}: ok (answered)", "codex:bad: unavailable (m)", "codex: ok (Codex's default model)"])

    def test_every_harness_row_is_probed_through_its_own_probe(self):
        row = {**fc_harness.HARNESSES.get("codex", {}), "name": "Other", "probe": mock.Mock(return_value=["other-probe"]), "result": mock.Mock(return_value=(True, "fine"))}
        p = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.dict(fc_harness.HARNESSES, {"other": row}), mock.patch.object(fc_config, "CREW_MODELS", {"a": "other:m"}), mock.patch.object(fc_config, "CREW_FALLBACK", {}):
            self.assertEqual((fc_models.probe_command("other:m"), fc_models.probe_result("other:m", p)), (["other-probe"], (True, "fine")))
            row["probe"].assert_called_once_with("m"); row["result"].assert_called_once_with(p)
            for model in ("other", "other:"): self.assertEqual(fc_models.model_available(model), (True, "Other's default model"))
            self.assertEqual((fc_models.model_available("other:m"), self.calls), ((True, "fine"), [["other-probe"]]))
            out = []
            with mock.patch("builtins.print", lambda *a: out.append(" ".join(map(str, a)))): fc_models.cmd_models(SimpleNamespace(probe=True))
        self.assertEqual(out, ["other:m: ok (fine)"])

    def test_claude_and_pi_are_unchanged_and_grok_is_skipped(self):
        self.assertEqual(fc_models.probe_command("pi:a/b")[0], "pi")
        self.assertEqual(fc_models.probe_command("claude:opus")[:4], ["claude", "-p", "--model", "opus"])
        probed = []
        with mock.patch.object(fc_config, "CREW_MODELS", {"a": "grok:x", "b": "pi:a/b", "c": "claude:opus", "d": "gemini:y"}), mock.patch.object(fc_config, "CREW_FALLBACK", {}), \
                mock.patch.object(fc_models, "model_available", lambda m: probed.append(m) or (True, "ok")), mock.patch("builtins.print"):
            fc_models.cmd_models(SimpleNamespace(probe=True))
        self.assertEqual(probed, ["pi:a/b", "claude:opus"])


class ClaudeOptional(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co, self.elsewhere = tmp / "bin", tmp / "home", tmp / "co", tmp / "elsewhere"
        for d in (self.bin, self.home, self.co / "bin", self.elsewhere): d.mkdir(parents=True)
        for f in ("bin/compose.py", "SKILL.md"): (self.co / f).write_text("")  # a compose checkout
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)

    def exe(self, name):
        (self.bin / name).write_text("#!/bin/sh\n"); (self.bin / name).chmod(stat.S_IRWXU)

    def link(self, hidden, target):
        link = self.home / hidden / "skills/compose"
        link.parent.mkdir(parents=True); link.symlink_to(target)

    def second(self):
        self.exe("other")
        row = {**fc_harness.HARNESSES.get("codex", {}), "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}
        p = mock.patch.dict(fc_harness.HARNESSES, {"other": row}); p.start(); self.addCleanup(p.stop)

    def test_claude_only_names_are_steps_rows(self):
        self.assertEqual(fc_steps.CLAUDE_ONLY, ("claude", "herdr skill", "i-have-adhd skill", "compose skill link"))
        self.assertLessEqual(set(fc_steps.CLAUDE_ONLY), {r[0] for r in fc_steps.STEPS})

    def test_other_harness_is_codex_only_with_the_binary_and_a_link_to_the_checkout(self):
        self.assertIsNone(fc_steps.other_harness(self.co))
        self.link(".codex", self.co)
        self.assertIsNone(fc_steps.other_harness(self.co))  # the link without codex on PATH
        self.exe("codex")
        self.assertEqual(fc_steps.other_harness(self.co), "codex")

    def test_other_harness_needs_the_link_to_point_at_the_checkout(self):
        self.exe("codex")
        self.assertIsNone(fc_steps.other_harness(self.co))  # codex on PATH, no link
        self.link(".codex", self.elsewhere)
        self.assertIsNone(fc_steps.other_harness(self.co))

    def test_other_harness_is_the_first_installed_row_whose_own_link_is_ok(self):
        self.exe("codex"); self.second(); self.link(".other", self.co)
        self.assertEqual(fc_steps.other_harness(self.co), "other")  # codex has no link
        self.link(".codex", self.co)
        self.assertEqual(fc_steps.other_harness(self.co), "codex")

    def test_required_drops_only_claude_only_rows_and_only_while_other_is_set(self):
        for row in fc_steps.STEPS:
            with self.subTest(row=row[0]):
                self.assertEqual(fc_steps.required(row, None), row[3] == "required")
                self.assertEqual(fc_steps.required(row, "codex"), row[3] == "required" and row[0] not in fc_steps.CLAUDE_ONLY)
        by = {r[0]: r for r in fc_steps.STEPS}
        for name in ("git", "herdr", "pi"): self.assertTrue(fc_steps.required(by[name], "codex"))
        for name in fc_steps.CLAUDE_ONLY: self.assertEqual((fc_steps.required(by[name], "codex"), fc_steps.required(by[name], None)), (False, True))
        for level in ("default", "designer"):
            row = next(r for r in fc_steps.STEPS if r[3] == level)
            self.assertEqual((fc_steps.required(row, None), fc_steps.required(row, "codex")), (False, False))


import fc_finish, fc_prompt, fc_setup
ONLY_CLAUDE, NOT_READY = ("claude", "herdr skill", "i-have-adhd skill", "compose skill link"), "compose is installed but not ready:"


class FinishWithoutClaude(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co = tmp / "bin", tmp / "home", Path(fc_finish.__file__).resolve().parents[1]
        self.bin.mkdir(); self.home.mkdir(); (tmp / "CONFIG_PATH").write_text("{}")
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home), "HERDR_ENV": "1"}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)
        for name in ("CONFIG_PATH", "AUTH_PATH", "ENV_FILE"):
            q = mock.patch.object(fc_config, name, tmp / name); q.start(); self.addCleanup(q.stop)

    def tools(self, claude=False, codex=False, link=None):
        for name in ("claude",) * claude + ("codex",) * codex:  # Codex is set up with codex and a skill link to this checkout; `link` alone overrides the link
            (self.bin / name).write_text("#!/bin/sh\n"); (self.bin / name).chmod(stat.S_IRWXU)
        if codex if link is None else link:
            (self.home / ".codex/skills").mkdir(parents=True); (self.home / ".codex/skills/compose").symlink_to(self.co)

    def finish(self, *failed):  # (lines, code, the rows listed as not ready)
        lines, code = fc_finish.finish([(n, "failed") for n in failed], True)
        return lines, code, lines[lines.index(NOT_READY) + 1:-1] if NOT_READY in lines else []

    def walk(self):  # the rows whose skip says compose stops working without them
        seen = {}
        with mock.patch.object(fc_prompt, "confirm", lambda *a: False), mock.patch.object(fc_prompt, "step", lambda name, word, lines=(): seen.update({name: list(lines)})):
            fc_setup.walk_steps(self.co, True, True)
        return {n for n, lines in seen.items() if any(l.startswith("compose stops working without it") for l in lines)}

    def test_codex_set_up_without_claude_is_ready_and_points_at_codex(self):
        self.tools(codex=True)
        lines, code, _ = self.finish(*ONLY_CLAUDE)
        self.assertEqual((code, lines[-2:]), (0, ["compose is ready", "next: run codex in a pane and type $compose"]))
        os.environ["HERDR_ENV"] = ""
        self.assertEqual(self.finish()[0][-1], "next: run compose to open herdr")

    def test_the_next_line_names_the_exe_of_the_harness_row_that_is_set_up(self):
        (self.bin / "other").write_text("#!/bin/sh\n"); (self.bin / "other").chmod(stat.S_IRWXU)
        (self.home / ".other/skills").mkdir(parents=True); (self.home / ".other/skills/compose").symlink_to(self.co)
        p = mock.patch.dict(fc_harness.HARNESSES, {"other": {**fc_harness.HARNESSES.get("codex", {}), "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}})
        p.start(); self.addCleanup(p.stop)
        lines, code, _ = self.finish(*ONLY_CLAUDE)
        self.assertEqual((code, lines[-2:]), (0, ["compose is ready", "next: run other in a pane and type $compose"]))

    def test_codex_set_up_without_claude_still_lists_git_and_herdr(self):
        self.tools(codex=True)
        _, code, rows = self.finish("git", "herdr", *ONLY_CLAUDE)
        self.assertEqual((code, [r.split(":")[0] for r in rows]), (0, ["  git", "  herdr"]))

    def test_without_claude_and_codex_not_set_up_finish_stops(self):
        for tools in ({}, {"codex": True, "link": False}, {"link": True}):  # the binary or the link alone is not set up
            self.setUp(); self.tools(**tools); lines, code, _ = self.finish()
            self.assertEqual((code, lines[-1]), (1, fc_finish.CLAUDE_MISSING), tools)

    def test_with_claude_the_next_line_names_claude(self):
        for codex in (False, True):
            self.setUp(); self.tools(claude=True, codex=codex); lines, code, _ = self.finish()
            self.assertEqual((code, lines[-1]), (0, "next: run claude in a pane and type /compose"), codex)

    def test_custom_flow_warns_about_skipping_only_what_compose_needs(self):
        required = {r[0] for r in fc_steps.STEPS if r[3] == "required" and r[5] != "key"}
        self.tools(codex=True)
        self.assertEqual(self.walk(), required - set(ONLY_CLAUDE))
        self.setUp(); self.tools()
        self.assertEqual(self.walk(), required)


CLAUDE_LINE = "MISSING: claude (install: curl -fsSL https://claude.ai/install.sh | bash)"
OPTIONAL = " - optional, Codex is set up"


class DoctorWithoutClaude(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co = tmp / "bin", tmp / "home", Path(fc_init.__file__).resolve().parents[1]
        self.bin.mkdir(); self.home.mkdir()
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)

    def tools(self, claude=False, codex=False, link=False):  # Codex is set up with the binary and a skill link to this checkout
        for name in ("claude",) * claude + ("codex",) * codex:
            (self.bin / name).write_text("#!/bin/sh\n"); (self.bin / name).chmod(stat.S_IRWXU)
        if link:
            (self.home / ".codex/skills").mkdir(parents=True); (self.home / ".codex/skills/compose").symlink_to(self.co)

    def deps(self):  # (the rows returned, the MISSING lines by row name, the waiting line)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            bad = fc_init.check_deps()
        lines = out.getvalue().splitlines()
        return bad, {l[len("MISSING: "):].split(" (")[0].split(":")[0]: l for l in lines if l.startswith("MISSING: ")}, [l for l in lines if l.startswith("waiting on Claude Code:")]

    def test_codex_set_up_without_claude_makes_the_claude_rows_optional(self):
        self.tools(codex=True, link=True)
        bad, lines, waiting = self.deps()
        self.assertFalse(set(bad) & set(ONLY_CLAUDE))
        self.assertIn("git", bad)
        self.assertEqual(lines["claude"], CLAUDE_LINE + " - optional, Codex is set up")
        for name in ("herdr skill", "compose skill link"): self.assertTrue(lines[name].endswith(OPTIONAL), lines[name])
        self.assertEqual(len(waiting), 1)
        self.assertIn("i-have-adhd skill", waiting[0])

    def test_codex_set_up_with_claude_installed_still_makes_its_rows_optional(self):
        self.tools(claude=True, codex=True, link=True)
        bad, lines, waiting = self.deps()
        self.assertFalse(set(bad) & set(ONLY_CLAUDE))
        self.assertNotIn("claude", lines)
        for name in ("herdr skill", "i-have-adhd skill", "compose skill link"): self.assertTrue(lines[name].endswith(OPTIONAL), lines[name])

    def test_the_note_names_whichever_harness_row_is_set_up(self):
        row = {**fc_harness.HARNESSES.get("codex", {}), "name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}
        p = mock.patch.dict(fc_harness.HARNESSES, {"other": row}); p.start(); self.addCleanup(p.stop)
        (self.bin / "other").write_text("#!/bin/sh\n"); (self.bin / "other").chmod(stat.S_IRWXU)
        (self.home / ".other/skills").mkdir(parents=True); (self.home / ".other/skills/compose").symlink_to(self.co)
        bad, lines, waiting = self.deps()
        self.assertFalse(set(bad) & set(ONLY_CLAUDE))
        self.assertEqual(lines["claude"], CLAUDE_LINE + " - optional, Other is set up")

    def test_without_codex_set_up_the_claude_rows_read_as_today(self):
        for tools in ({}, {"codex": True}, {"link": True}):  # the binary or the link alone is not set up
            self.setUp(); self.tools(**tools); bad, lines, waiting = self.deps()
            self.assertTrue(set(ONLY_CLAUDE) <= set(bad), tools)
            self.assertEqual(lines["claude"], CLAUDE_LINE, tools)
            self.assertFalse(any(OPTIONAL in l for l in lines.values()), tools)
            self.assertEqual((len(waiting), "i-have-adhd skill" in waiting[0]), (1, True), tools)


class CodexArgv(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.tmp, self.results = Path(d.name), Path(d.name, "results")
        git = lambda *a, cwd: subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout.strip()
        def tree(name):  # a worktree of its own repo, with the dirs it needs: the shared one and its own
            main, wt = self.tmp / f"{name}-main", self.tmp / name
            main.mkdir(); git("init", "-q", cwd=main); git("commit", "-q", "--allow-empty", "-m", "i", cwd=main); git("worktree", "add", "-q", "-b", name, str(wt), cwd=main)
            return wt, [str(Path(git(*a, cwd=wt)).resolve()) for a in (("rev-parse", "--path-format=absolute", "--git-common-dir"), ("rev-parse", "--absolute-git-dir"))]
        (self.cwd, self.dirs), (self.work, self.wdirs) = tree("cwd"), tree("work")
        self.clone = self.tmp / "clone"; self.clone.mkdir(); git("init", "-q", cwd=self.clone)

    def argv(self, model="codex:gpt-6.1-sol", effort="high", prompt="p", cwd=None, work=None):
        return [str(x) for x in fc_harness.crew_argv(model, effort, prompt, "/s/SKILL.md", cwd or self.cwd, self.results, work)]

    def adds(self, argv): return [v for f, v in zip(argv, argv[1:]) if f == "--add-dir"]

    def test_exact_list(self):
        trust = "projects={%s={trust_level=\"trusted\"}}" % json.dumps(os.path.realpath(self.cwd))
        text = json.dumps("p\n\nThe compose skill is the file /s/SKILL.md.")
        self.assertEqual(self.argv(), ["-m", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"', "-s", "workspace-write", "-a", "never",
                                       "-c", "sandbox_workspace_write.network_access=true", "-c", trust, "-c", "developer_instructions=" + text,
                                       "--add-dir", str(self.results), "--add-dir", self.dirs[0], "--add-dir", self.dirs[1]])

    def test_bare_codex_and_no_effort(self):
        for model in ("codex", "codex:"):
            argv = self.argv(model, None)
            self.assertNotIn("-m", argv)
            self.assertFalse([a for a in argv if "model_reasoning_effort" in a])
            self.assertEqual(argv[:2], ["-s", "workspace-write"])

    def test_work_goes_last_and_repeats_or_missing_repos_are_left_out(self):
        self.assertEqual(self.adds(self.argv(work=self.work)), [str(self.results), *self.dirs, str(self.work), *self.wdirs])
        self.assertEqual(self.adds(self.argv(work=self.cwd)), [str(self.results), *self.dirs, str(self.cwd)])  # its git dirs are already there
        self.assertEqual(self.adds(self.argv(cwd=self.clone)), [str(self.results), os.path.realpath(self.clone / ".git")])  # one git dir, not two
        self.assertEqual(self.adds(self.argv(work=self.tmp / "gone")), [str(self.results), *self.dirs, str(self.tmp / "gone")])  # not a folder: no git dirs asked
        outside = self.tmp / "plain"; outside.mkdir()
        self.assertEqual(self.adds(self.argv(cwd=outside)), [str(self.results)])  # no git dir to add

    def test_values_parse_as_toml_through_a_symlink(self):
        import tomllib
        link, prompt = self.tmp / "link", 'say "hi"\nthen \\ stop'
        link.symlink_to(self.cwd)
        values = {a.split("=", 1)[0]: tomllib.loads(a) for a in self.argv(cwd=link, prompt=prompt) if a.startswith(("projects=", "developer_instructions="))}
        self.assertEqual(values["projects"], {"projects": {os.path.realpath(self.cwd): {"trust_level": "trusted"}}})
        self.assertEqual(values["developer_instructions"]["developer_instructions"], prompt + "\n\nThe compose skill is the file /s/SKILL.md.")

    def test_no_unfenced_sandbox(self):
        for a in self.argv(work=self.work): self.assertFalse(a == "danger-full-access" or a.startswith("--dangerously"), a)


class CodexStart(unittest.TestCase):
    def start(self, model=None, entry="codex:gpt-6.1-sol", trusted=True):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"; proj.mkdir(parents=True)
        calls, ready = [], mock.Mock()
        skill = proj.parent / "skill"; skill.mkdir(); (skill / "SKILL.md").write_text("v1\n")
        def herdr(*args, **kw):
            calls.append(args)
            return {"agents": []} if args[:2] == ("agent", "list") else {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}} if args[:2] == ("tab", "create") else {"agent": {"agent_status": "working"}} if args[:2] == ("agent", "get") else {}
        a = type("A", (), {"action": "start", "role": "tester", "title": "t", "brief": "b", "model": model})
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "herdr", herdr), mock.patch.object(fc.fc_herdr, "herdr_ready", ready), \
                mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_herdr, "herdr_space", return_value="w9"), mock.patch.object(fc.fc_herdr, "herdr_find_space", return_value="w9"), \
                mock.patch.object(fc.fc_frame0, "frame0_register"), mock.patch.object(fc.fc_claude, "claude_trusted", return_value=trusted), mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")), \
                mock.patch.object(fc.fc_mcp, "installed_servers", return_value=[]), mock.patch.object(fc.fc_config, "CREW_MODELS", {"tester": entry}), mock.patch.object(fc.fc_config, "CREW_EFFORT", {"tester": "high"}), \
                mock.patch.object(fc.fc_hooks, "SKILL_DIR", skill), mock.patch("builtins.print"):
            fc.fc_crew.cmd_crew(a)
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        return start, ready, json.loads(next(fc.fc_crew.crew_dir(proj).glob("*.json")).read_text()), proj, calls

    def test_codex_role_starts_with_crew_argv_and_never_waits_for_ready(self):
        start, ready, rec, proj, calls = self.start(trusted=False)  # a folder Claude Code does not trust
        self.assertEqual((start[3:10], rec["effort"], "skill" in rec), (("--kind", "codex", "--pane", "w9:p7", "--timeout", "60000", "--"), "high", True))
        argv = fc_harness.crew_argv("codex:gpt-6.1-sol", "high", fc.fc_crew.TRUST_PROMPT, fc.fc_crew.CLI_REPO / "SKILL.md", rec["cwd"], fc.fc_crew.crew_dir(proj).parent, None)
        self.assertEqual([str(x) for x in start[10:]], [str(x) for x in argv])
        ready.assert_not_called()
        self.assertFalse([c for c in calls if any("key" in str(x) for x in c[:2])])  # Codex's "Hooks need review" dialog is never answered

    def test_model_flag_codex_ids_start_as_codex(self):
        for m in ("codex", "codex:x"):
            start, ready = self.start(m)[:2]
            self.assertEqual((start[4], "-m" in start, ready.called), ("codex", m != "codex", False))

    def test_claude_and_pi_roles_start_as_before(self):
        start, ready, rec = self.start(entry="claude:claude-sonnet-5-5")[:3]
        self.assertEqual((start[4], ready.call_count, "skill" in rec, self.start(entry="pi:x/y")[0][4]), ("claude", 1, False, "pi"))
        with self.assertRaises(SystemExit): self.start(entry="claude:claude-sonnet-5-5", trusted=False)  # only a Codex teammate skips the trust check

    def test_crew_pick_full_accepts_codex_and_refuses_the_rest_exactly(self):
        with mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")):
            for m in ("codex", "codex:x"): self.assertEqual(fc.fc_crew.crew_pick_full("tester", m)[0], m)
        def refusal(label, where): return (f"{label} is 'codex/x', but teammate sessions run in Claude Code, pi, or Codex: use claude:<model-id> (e.g. claude:claude-sonnet-5-5), "
                                           f"pi:<provider/model> (e.g. pi:openai/gpt-6-astra), or codex:<model> (e.g. codex:gpt-6.1-sol){where}; OpenCode ids are for implementers only")
        with self.assertRaises(SystemExit) as e: fc.fc_crew.crew_pick_full("tester", "codex/x")
        self.assertEqual(str(e.exception), refusal("--model", ""))
        with mock.patch.object(fc.fc_config, "CREW_MODELS", {"tester": "codex/x"}), self.assertRaises(SystemExit) as e: fc.fc_crew.crew_pick_full("tester")
        self.assertEqual(str(e.exception), refusal("models.crew.tester", f" in {fc.fc_config.CONFIG_PATH}"))
        with self.assertRaises(SystemExit): fc.fc_crew.crew_pick_full("tester", "grok:x")


class HarnessTable(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home = tmp / "bin", tmp / "home"
        for d in (self.bin, self.home): d.mkdir()
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)

    def exe(self, name, mode=stat.S_IRWXU):
        (self.bin / name).write_text("#!/bin/sh\n"); (self.bin / name).chmod(mode)

    def test_the_table_holds_the_codex_row_first_and_two_name_only_entries(self):
        h = fc_harness
        self.assertEqual((h.RESERVED, h.HARNESSES["gemini"], h.HARNESSES["grok"]), (("codex", "gemini", "grok"), {}, {}))
        self.assertEqual({k: v for k, v in h.HARNESSES["codex"].items() if k != "hooks"}, {"name": "Codex", "kind": "codex", "exe": "codex", "home_env": "CODEX_HOME", "home": "~/.codex", "sigil": "$", "example": "gpt-6.1-sol",
                                                "herdr_ready": False, "probe": h._codex_probe, "result": h._codex_result, "argv": h._codex_argv,
                                                "hooks_file": "hooks.json", "trust_file": "config.toml", "hash": h._codex_hash})

    def test_harness_of_and_model_id_read_only_a_key_that_has_fields(self):
        for m, want in (("codex", ("codex", None)), ("codex:", ("codex", None)), ("codex:gpt-6-sol", ("codex", "gpt-6-sol")), ("codex:a:b", ("codex", "a:b")),
                        ("gemini:x", (None, None)), ("grok", (None, None)), ("grok:x", (None, None)), ("codex/gpt-6-sol", (None, None)), ("codexx:y", (None, None)),
                        ("Codex:x", (None, None)), ("claude:opus", (None, None)), ("pi:x/y", (None, None)), ("", (None, None)), (None, (None, None))):
            self.assertEqual((fc_harness.harness_of(m), fc_harness.model_id(m)), want, m)

    def test_a_row_with_fields_is_named_by_its_key_and_listed_in_table_order(self):
        self.exe("other")
        with mock.patch.dict(fc_harness.HARNESSES, {"other": {"name": "Other", "exe": "other", "home_env": "OTHER_HOME", "home": "~/.other"}}):
            self.assertEqual((fc_harness.harness_of("other:m"), fc_harness.model_id("other:m"), fc_harness.rows(), fc_harness.installed()), ("other", "m", ["codex", "other"], ["other"]))
            self.exe("codex"); self.assertEqual(fc_harness.installed(), ["codex", "other"])
            os.environ["OTHER_HOME"] = str(self.home / "o"); self.assertEqual(fc_harness.skills_dir("other"), self.home / "o/skills")

    def test_rows_is_codex_and_installed_needs_an_executable_codex_on_path(self):
        self.assertEqual((fc_harness.rows(), fc_harness.installed()), (["codex"], []))
        self.exe("codex", stat.S_IRUSR | stat.S_IWUSR); self.assertEqual(fc_harness.installed(), [])
        self.exe("codex"); self.assertEqual(fc_harness.installed(), ["codex"])

    def test_skills_dir_prefers_a_non_empty_codex_home_and_reads_home_at_call_time(self):
        self.assertEqual(fc_harness.skills_dir("codex"), self.home / ".codex/skills")
        os.environ["CODEX_HOME"] = ""; self.assertEqual(fc_harness.skills_dir("codex"), self.home / ".codex/skills")
        os.environ["HOME"] = str(self.home / "moved"); self.assertEqual(fc_harness.skills_dir("codex"), self.home / "moved/.codex/skills")
        os.environ["CODEX_HOME"] = str(self.home / "elsewhere"); self.assertEqual(fc_harness.skills_dir("codex"), self.home / "elsewhere/skills")


class HookFields(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)

    def digest(self, event, matcher, hooks):
        o = {"event_name": event, "hooks": hooks}
        if matcher: o["matcher"] = matcher
        return "sha256:" + hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def test_the_codex_row_gains_the_hooks_file_trust_file_hash_and_four_hooks(self):
        row = fc_harness.HARNESSES["codex"]
        self.assertEqual((row["hooks_file"], row["trust_file"], row["hash"]), ("hooks.json", "config.toml", fc_harness._codex_hash))
        self.assertEqual(row["hooks"], (("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit", "guard"), ("PreToolUse", "Bash", "guard"), ("UserPromptSubmit", None, "skillcheck"), ("SessionStart", "compact", "reenter")))

    def test_hash_is_the_sha256_of_the_sorted_compact_json_with_defaults_filled_in(self):
        h = fc_harness._codex_hash
        c = {"type": "command", "command": '"/c/bin/compose" guard'}
        self.assertEqual(h("PreToolUse", {"matcher": "Bash", "hooks": [{**c, "timeout": 10}]}), self.digest("pre_tool_use", "Bash", [{**c, "timeout": 10, "async": False}]))
        self.assertEqual(h("UserPromptSubmit", {"hooks": [c]}), self.digest("user_prompt_submit", None, [{**c, "timeout": 600, "async": False}]))
        full = {**c, "timeout": 5, "async": True, "statusMessage": "checking"}
        self.assertEqual(h("SessionStart", {"matcher": "compact", "hooks": [full, c]}), self.digest("session_start", "compact", [full, {**c, "timeout": 600, "async": False}]))

    def test_home_dir_prefers_a_non_empty_codex_home_and_reads_the_environment_at_call_time(self):
        self.assertEqual(fc_harness.home_dir("codex"), self.home / ".codex")
        os.environ["CODEX_HOME"] = ""; self.assertEqual(fc_harness.home_dir("codex"), self.home / ".codex")
        os.environ["HOME"] = str(self.home / "moved"); self.assertEqual(fc_harness.home_dir("codex"), self.home / "moved/.codex")
        os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        self.assertEqual((fc_harness.home_dir("codex"), fc_harness.skills_dir("codex")), (self.home / "elsewhere", self.home / "elsewhere/skills"))

    def test_hook_groups_for_codex_are_the_four_groups_under_three_events(self):
        def g(m, sub, co="/c"):
            return {**({"matcher": m} if m else {}), "hooks": [{"type": "command", "command": f'"{co}/bin/compose" {sub}', "timeout": 10}]}
        want = {"PreToolUse": [g("Write|Edit|MultiEdit|NotebookEdit", "guard"), g("Bash", "guard")], "UserPromptSubmit": [g(None, "skillcheck")], "SessionStart": [g("compact", "reenter")]}
        self.assertEqual(fc_harness.hook_groups("codex", "/c"), want)
        self.assertEqual(fc_harness.hook_groups("codex", "/a b")["UserPromptSubmit"], [g(None, "skillcheck", "/a b")])

    def test_hook_groups_is_empty_for_a_row_without_hooks_and_follows_any_row_with_them(self):
        self.assertEqual((fc_harness.hook_groups("grok", "/c"), fc_harness.hook_groups("gemini", "/c")), ({}, {}))
        with mock.patch.dict(fc_harness.HARNESSES, {"other": {"name": "Other", "hooks": (("Ev", None, "a"), ("Ev", "m", "b"))}, "bare": {"name": "Bare"}}):
            self.assertEqual(fc_harness.hook_groups("bare", "/c"), {})
            self.assertEqual(fc_harness.hook_groups("other", "/c"), {"Ev": [{"hooks": [{"type": "command", "command": '"/c/bin/compose" a', "timeout": 10}]},
                                                                      {"matcher": "m", "hooks": [{"type": "command", "command": '"/c/bin/compose" b', "timeout": 10}]}]})


class HooksFile(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": str(self.home / "codex")}); p.start(); self.addCleanup(p.stop)
        (self.home / "codex").mkdir()
        self.file, self.want = self.home / "codex/hooks.json", self.groups("/c")

    def groups(self, co):
        def g(m, sub): return {**({"matcher": m} if m else {}), "hooks": [{"type": "command", "command": f'"{co}/bin/compose" {sub}', "timeout": 10}]}
        return {"PreToolUse": [g("Write|Edit|MultiEdit|NotebookEdit", "guard"), g("Bash", "guard")], "UserPromptSubmit": [g(None, "skillcheck")], "SessionStart": [g("compact", "reenter")]}

    def put(self, doc): self.file.write_text(doc if isinstance(doc, str) else json.dumps(doc))

    def test_a_missing_file_gets_the_four_groups_and_a_second_call_writes_nothing(self):
        self.assertEqual([str(p) for p in fc_links.write_hooks("codex", "/c")], [str(self.file)])
        self.assertEqual(json.loads(self.file.read_text()), {"hooks": self.want})
        self.assertIn('\n  "hooks": {', self.file.read_text())
        before = self.file.read_bytes()
        self.assertEqual((fc_links.write_hooks("codex", "/c"), self.file.read_bytes()), ([], before))
        self.assertEqual([p.name for p in (self.home / "codex").iterdir()], ["hooks.json"])

    def test_herdrs_group_keeps_its_index_and_compose_appends_after_it(self):
        herdr = {"hooks": [{"type": "command", "command": "herdr hook session-start"}]}
        self.put({"theme": "dark", "hooks": {"SessionStart": [herdr], "Stop": [herdr]}})
        self.assertEqual(len(fc_links.write_hooks("codex", "/c")), 1)
        doc = json.loads(self.file.read_text())
        self.assertEqual(doc["hooks"], {**self.want, "SessionStart": [herdr, *self.want["SessionStart"]], "Stop": [herdr]})
        self.assertEqual(doc["theme"], "dark")

    def test_a_compose_group_of_another_checkout_is_replaced_at_its_index_and_an_equal_one_is_kept(self):
        herdr = {"hooks": [{"type": "command", "command": "herdr hook"}]}
        old = self.groups("/old")
        self.put({"hooks": {"UserPromptSubmit": [herdr, old["UserPromptSubmit"][0]], "SessionStart": [self.want["SessionStart"][0], herdr]}})
        fc_links.write_hooks("codex", "/c")
        doc = json.loads(self.file.read_text())["hooks"]
        self.assertEqual(doc["UserPromptSubmit"], [herdr, *self.want["UserPromptSubmit"]])
        self.assertEqual(doc["SessionStart"], [*self.want["SessionStart"], herdr])

    def test_invalid_json_exits_naming_the_file_and_writes_nothing(self):
        self.put("{not json")
        with self.assertRaises(SystemExit) as e: fc_links.write_hooks("codex", "/c")
        self.assertIn(str(self.file), str(e.exception))
        self.assertEqual((self.file.read_text(), sorted(p.name for p in (self.home / "codex").iterdir())), ("{not json", ["hooks.json"]))

    def test_a_row_without_hooks_writes_nothing(self):
        row = {"name": "Other", "home_env": "CODEX_HOME", "home": "~/.codex", "hooks_file": "hooks.json"}
        with mock.patch.dict(fc_harness.HARNESSES, {"other": row}): self.assertEqual(fc_links.write_hooks("other", "/c"), [])
        self.assertFalse(self.file.exists())


class HookTrust(unittest.TestCase):
    SNAKE = {"PreToolUse": "pre_tool_use", "UserPromptSubmit": "user_prompt_submit", "SessionStart": "session_start"}
    def setUp(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.home, self.bin = tmp / "home", tmp / "bin"
        (self.home / "codex").mkdir(parents=True); self.bin.mkdir()
        p = mock.patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": str(self.home / "codex"), "PATH": str(self.bin)}); p.start(); self.addCleanup(p.stop)
        self.file, self.trust = self.home / "codex/hooks.json", self.home / "codex/config.toml"
        g = lambda m, sub: {**({"matcher": m} if m else {}), "hooks": [{"type": "command", "command": f'"/c/bin/compose" {sub}', "timeout": 10}]}
        self.put({"PreToolUse": [g("Write|Edit|MultiEdit|NotebookEdit", "guard"), g("Bash", "guard")], "UserPromptSubmit": [g(None, "skillcheck")], "SessionStart": [g("compact", "reenter")]})

    def put(self, hooks): self.file.write_text(json.dumps({"hooks": hooks}))
    def hooks(self): return json.loads(self.file.read_text())["hooks"]
    def records(self):
        return {f"{self.file}:{self.SNAKE[ev]}:{i}:{j}": fc_harness._codex_hash(ev, g)
                for ev, gs in self.hooks().items() for i, g in enumerate(gs) for j in range(len(g["hooks"]))}

    def state(self): return {k: v["trusted_hash"] for k, v in tomllib.loads(self.trust.read_text())["hooks"]["state"].items()}

    def test_four_records_are_written_with_the_hashes_and_a_second_call_writes_nothing(self):
        self.assertEqual([str(p) for p in fc_links.trust_hooks("codex", "/c")], [str(self.trust)])
        self.assertEqual(self.state(), self.records())
        self.assertIn(f"[hooks.state.{json.dumps(f'{self.file}:pre_tool_use:1:0')}]", self.trust.read_text())
        before = self.trust.read_bytes(); self.assertEqual((fc_links.trust_hooks("codex", "/c"), self.trust.read_bytes()), ([], before))

    def test_other_content_and_herdrs_record_stay_and_herdrs_group_gets_none(self):
        herdr = {"hooks": [{"type": "command", "command": "herdr hook session-start"}]}; self.put({**self.hooks(), "SessionStart": [herdr, *self.hooks()["SessionStart"]]})
        hk = f"{self.file}:session_start:0:0"
        old = f'# mine\nmodel = "x"\n\n[projects."{self.home}"]\ntrust_level = "trusted"  # keep\n\n[hooks.state.{json.dumps(hk)}]\ntrusted_hash = "sha256:herdr"\n'
        self.trust.write_text(old)
        fc_links.trust_hooks("codex", "/c")
        self.assertTrue(self.trust.read_text().startswith(old))
        self.assertEqual(self.state(), {**{k: v for k, v in self.records().items() if k != hk}, hk: "sha256:herdr"})

    def test_a_wrong_hash_has_only_its_trusted_hash_line_replaced(self):
        key = f"{self.file}:pre_tool_use:0:0"
        old = f'# top\n[hooks.state.{json.dumps(key)}]\nenabled = true\ntrusted_hash = "sha256:bad"\n\n[other]\ntrusted_hash = "keep"\n'
        self.trust.write_text(old)
        fc_links.trust_hooks("codex", "/c")
        self.assertTrue(self.trust.read_text().startswith(old.replace('"sha256:bad"', json.dumps(self.records()[key]))))
        self.assertEqual((self.state(), tomllib.loads(self.trust.read_text())["other"]), (self.records(), {"trusted_hash": "keep"}))

    def test_invalid_toml_or_a_header_not_found_as_text_exits_naming_the_file_and_writes_nothing(self):
        for text in ("[unclosed", f'[hooks.state]\n{json.dumps(f"{self.file}:pre_tool_use:0:0")} = {{ trusted_hash = "sha256:bad" }}\n'):
            self.trust.write_text(text)
            with self.assertRaises(SystemExit) as e: fc_links.trust_hooks("codex", "/c")
            self.assertIn(str(self.trust), str(e.exception))
            self.assertEqual(self.trust.read_text(), text)

    def test_hooks_ok_names_the_first_missing_hook_or_record_and_passes_after_both_writes(self):
        self.assertEqual(fc_checks.hooks_ok("codex", "/c"), (True, ""))
        (self.bin / "codex").write_text("#!/bin/sh\n"); (self.bin / "codex").chmod(stat.S_IRWXU)
        hooks = self.hooks(); self.file.unlink()
        ok, why = fc_checks.hooks_ok("codex", "/c"); self.assertFalse(ok); self.assertIn("hooks.json", why); self.assertTrue(why.endswith("lacks compose's guard hook"), why)
        self.put(hooks)
        ok, why = fc_checks.hooks_ok("codex", "/c"); self.assertFalse(ok); self.assertIn("config.toml", why); self.assertTrue(why.endswith("has no trust record for compose's guard hook"), why)
        fc_links.trust_hooks("codex", "/c"); self.assertEqual(fc_checks.hooks_ok("codex", "/c"), (True, ""))
        self.trust.write_text(self.trust.read_text().replace(self.records()[f"{self.file}:session_start:0:0"], "sha256:bad"))
        self.assertTrue(fc_checks.hooks_ok("codex", "/c")[1].endswith("has no trust record for compose's reenter hook"))
        with mock.patch.dict(fc_harness.HARNESSES, {"codex": {k: v for k, v in fc_harness.HARNESSES["codex"].items() if k != "hooks"}}): self.assertEqual(fc_checks.hooks_ok("codex", "/c"), (True, ""))


class CodexGuard(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        fc.fc_core.sh(["git", "init", "-q"], self.repo)
        d = Path(tempfile.mkdtemp())
        (d / "skill").mkdir(); (d / "skill" / "SKILL.md").write_text("v1\n")
        for p in (mock.patch.object(fc.fc_hooks, "SKILL_DIR", d / "skill"), mock.patch.object(fc.fc_hooks, "SKILL_SEEN", d / "seen")):
            p.start(); self.addCleanup(p.stop)

    def run_hook(self, cmd, ev, role):
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"} | ({"COMPOSE_ROLE": role} if role else {})
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(ev))), mock.patch.object(sys, "stdout", out):
            cmd(None)
        return out.getvalue()

    def denied(self, tool, ti, role="orchestrator"):
        out = self.run_hook(fc.fc_hooks.cmd_guard, {"tool_name": tool, "cwd": str(self.repo), "tool_input": ti}, role)
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else None

    def patch(self, *lines):
        return {"command": "*** Begin Patch\n" + "\n".join(lines) + "\n*** End Patch"}

    def test_apply_patch_headers_are_denied_when_relative_paths_land_in_the_repo(self):
        self.assertEqual(self.denied("apply_patch", self.patch("*** Add File: a.go", "+x")), fc.fc_hooks.guard_decision("Write", str(self.repo / "a.go"), "orchestrator"))
        for head in ("*** Update File: src/a.go", "*** Delete File: src/a.go", "*** Update File: .compose/shop/scratch/a\n*** Move to: src/b.go",
                     "*** Add File: .compose/shop/scratch/a\n+x\n*** Update File: src/a.go\n@@"):
            self.assertIn("never edit code", self.denied("apply_patch", self.patch(head)) or "", head)

    def test_apply_patch_in_scratch_and_bash_without_a_target_are_allowed(self):
        self.assertIsNone(self.denied("apply_patch", self.patch("*** Add File: .compose/shop/scratch/x.json", "+{}")))
        self.assertIsNone(self.denied("Bash", {"command": "ls 2>&1"}))
        self.assertIsNone(self.denied("Bash", {"command": "ls -la && git status"}))
        self.assertIsNone(self.denied("Bash", {"command": "echo hi > .compose/shop/scratch/x"}))

    def test_bash_redirection_targets_are_denied(self):
        for cmd in ("echo hi > a.txt", "echo hi >> a.txt", "cat x 2>&1 > a.txt", "echo hi >a.txt", "ls | tee x > src/a.txt"):
            self.assertIn("never edit code", self.denied("Bash", {"command": cmd}) or "", cmd)

    def test_other_roles_and_claude_payloads(self):
        for role in ("crew", None, ""):
            self.assertIsNone(self.denied("apply_patch", self.patch("*** Add File: a.go"), role), role)
            self.assertIsNone(self.denied("Bash", {"command": "echo hi > a.txt"}, role), role)
        self.assertIn("never edit code", self.denied("Write", {"file_path": str(self.repo / "a.go")}))
        self.assertIsNone(self.denied("Write", {"file_path": str(self.repo / "a.go")}, "crew"))
        self.assertIsNone(self.denied("Read", {"file_path": str(self.repo / "a.go")}))

    def test_edit_paths_resolves_relative_paths_against_cwd(self):
        ev = {"tool_name": "apply_patch", "cwd": str(self.repo), "tool_input": self.patch("*** Add File: a", "*** Update File: b", "*** Delete File: /x/c", "*** Move to: d")}
        self.assertEqual({os.path.realpath(p) for p in fc.fc_hooks.edit_paths(ev)}, {os.path.realpath(self.repo / n) for n in "abd"} | {os.path.realpath("/x/c")})

    def test_a_sigil_prompt_enrolls_the_session_like_the_slash_command(self):
        def seen(prompt):
            self.run_hook(fc.fc_hooks.cmd_skillcheck, {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": prompt}, None)
            return fc.fc_hooks.SKILL_SEEN.exists() and (fc.fc_hooks.SKILL_SEEN / "s.json").exists()
        for p in ("$composer", "$compose:yolo", "compose-yolo", "go $compose"):
            self.assertFalse(seen(p), p)
        for p in ("$compose-yolo", "$compose", "$compose ship it"):
            self.assertTrue(seen(p), p)
            (fc.fc_hooks.SKILL_SEEN / "s.json").unlink()
