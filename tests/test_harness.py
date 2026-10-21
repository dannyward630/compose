import hermetic  # first: no test sees the real home
import contextlib, importlib.machinery, importlib.util, io, json, os, stat, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_checks, fc_config, fc_harness, fc_init, fc_links, fc_models, fc_steprun, fc_steps
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fc)


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

    def test_row_is_an_optional_default_write_row(self):
        self.assertEqual(self.row[2:], ("compose setup", "default", False, "write"))
        self.assertEqual(set(fc_steprun.WRITERS), set(fc_steprun.PREVIEWS))

    def test_without_codex_the_check_passes_and_run_step_does_nothing(self):
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

    def test_a_refused_copy_fails_the_step_with_the_writer_line(self):
        self.codex(); self.planner.mkdir(parents=True)
        state, line = self.run_row()
        self.assertEqual(state, "failed")
        self.assertIn("refused ~/.codex/skills/compose-planner/SKILL.md", line)

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


class ClaudeOptional(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co, self.other = tmp / "bin", tmp / "home", tmp / "co", tmp / "other"
        for d in (self.bin, self.home, self.co / "bin", self.other): d.mkdir(parents=True)
        for f in ("bin/compose.py", "SKILL.md"): (self.co / f).write_text("")  # a compose checkout
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CODEX_HOME", None)

    def codex(self):
        (self.bin / "codex").write_text("#!/bin/sh\n"); (self.bin / "codex").chmod(stat.S_IRWXU)

    def link(self, target):
        link = self.home / ".codex/skills/compose"
        link.parent.mkdir(parents=True); link.symlink_to(target)

    def test_claude_only_names_are_steps_rows(self):
        self.assertEqual(fc_steps.CLAUDE_ONLY, ("claude", "herdr skill", "i-have-adhd skill", "compose skill link"))
        self.assertLessEqual(set(fc_steps.CLAUDE_ONLY), {r[0] for r in fc_steps.STEPS})

    def test_other_harness_is_codex_only_with_the_binary_and_a_link_to_the_checkout(self):
        self.assertIsNone(fc_steps.other_harness(self.co))
        self.link(self.co)
        self.assertIsNone(fc_steps.other_harness(self.co))  # the link without codex on PATH
        self.codex()
        self.assertEqual(fc_steps.other_harness(self.co), "codex")

    def test_other_harness_needs_the_link_to_point_at_the_checkout(self):
        self.codex()
        self.assertIsNone(fc_steps.other_harness(self.co))  # codex on PATH, no link
        self.link(self.other)
        self.assertIsNone(fc_steps.other_harness(self.co))

    def test_required_drops_only_claude_only_rows_and_only_while_other_is_set(self):
        for row in fc_steps.STEPS:
            with self.subTest(row=row[0]):
                self.assertEqual(fc_steps.required(row, None), row[3] == "required")
                self.assertEqual(fc_steps.required(row, "Codex"), row[3] == "required" and row[0] not in fc_steps.CLAUDE_ONLY)
        by = {r[0]: r for r in fc_steps.STEPS}
        for name in ("git", "herdr", "pi"): self.assertTrue(fc_steps.required(by[name], "Codex"))
        for name in fc_steps.CLAUDE_ONLY: self.assertEqual((fc_steps.required(by[name], "Codex"), fc_steps.required(by[name], None)), (False, True))
        for level in ("default", "designer"):
            row = next(r for r in fc_steps.STEPS if r[3] == level)
            self.assertEqual((fc_steps.required(row, None), fc_steps.required(row, "Codex")), (False, False))


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

    def test_without_codex_set_up_the_claude_rows_read_as_today(self):
        for tools in ({}, {"codex": True}, {"link": True}):  # the binary or the link alone is not set up
            self.setUp(); self.tools(**tools); bad, lines, waiting = self.deps()
            self.assertTrue(set(ONLY_CLAUDE) <= set(bad), tools)
            self.assertEqual(lines["claude"], CLAUDE_LINE, tools)
            self.assertFalse(any(OPTIONAL in l for l in lines.values()), tools)
            self.assertEqual((len(waiting), "i-have-adhd skill" in waiting[0]), (1, True), tools)
