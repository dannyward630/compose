import hermetic  # first: no test sees the real home
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
import os
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_finish as F
import fc_herdrconf, fc_links
ALL = {"workspaces": {"default": {"openrouter": "sk-or-test", "linear": "lin-test"}}, "typesafe": "ts-test"}
READY, NOT_DONE = ["compose is ready", "next: run compose to open herdr"], "setup is not finished"
SKIPS = lambda lines: [l for l in lines if l.startswith("skipped")]
CLAUDE = "Claude Code is missing: install it with curl -fsSL https://claude.ai/install.sh | bash, log in, then run compose setup again"

class Finish(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp()); self.cfg, self.auth = tmp / "config.json", tmp / "auth.json"
        self.cfg.write_text(json.dumps({"workspaces": {"w": {"target": "x"}}, "models": {"implementer": "pi:mine"}}))
        self.probe, self.claude, self.connected = mock.Mock(return_value=(True, ["probe passed"])), True, False
        self.herdr, self.path = mock.Mock(return_value=("ok", [])), None
        for p in (mock.patch.object(F.fc_config, "CONFIG_PATH", self.cfg), mock.patch.object(F.fc_config, "AUTH_PATH", self.auth),
                  mock.patch.object(F.fc_config, "ENV_FILE", tmp / ".env"), mock.patch.object(F.fc_steps, "FRAMELINK_ENV", tmp / "figma.env"),
                  mock.patch.object(F.fc_defaults, "probe_implementer", self.probe),
                  mock.patch.object(fc_herdrconf, "apply_herdr_config", self.herdr), mock.patch.object(fc_links, "path_line", lambda: self.path),
                  mock.patch.object(F.fc_keys, "linear_connected", lambda: self.connected),
                  mock.patch.object(F.fc_keys, "skipped_line", lambda kind, ws: f"skipped {kind}"),
                  mock.patch.object(F.shutil, "which", lambda n, *a, **k: None if n == "claude" and not self.claude else f"/bin/{n}")):
            p.start(); self.addCleanup(p.stop)

    def run_finish(self, auth, yes=False):
        self.auth.write_text(json.dumps(auth))
        lines, code = F.finish([("pi", "ok"), ("OpenRouter key", "skipped")], yes)
        self.assertNotIn("sk-or-test", "\n".join(lines)); return lines, code

    def test_ready_merges_models_once_keeps_values_and_probes(self):
        before = json.loads(self.cfg.read_text())
        lines, code = self.run_finish(ALL)
        merged, added = F.fc_defaults.merge_models(before)
        self.assertEqual((code, lines[-2:]), (0, READY))
        self.assertTrue(set(added) <= set(lines) and added and set(F.fc_defaults.PRESET_STEPS) <= set(lines))
        self.assertIn("probe passed", lines); self.assertEqual(SKIPS(lines), [])
        self.assertEqual(json.loads(self.cfg.read_text()), merged); self.assertEqual(merged["models"]["implementer"], "pi:mine")
        again = self.run_finish(ALL)
        self.assertEqual(again, self.run_finish(ALL)); self.assertFalse(set(added) & set(again[0]))
        self.assertEqual(json.loads(self.cfg.read_text()), merged)

    def test_missing_keys_and_linear_states(self):
        bare = {"workspaces": {"default": {}}}
        for self.connected, linear in ((True, []), (False, ["linear"]), (None, ["linear"])):
            skipped = [f"skipped {k}" for k in ["openrouter", "typesafe", *linear]]
            lines, code = self.run_finish(bare)
            self.assertEqual((code, lines[-1], SKIPS(lines)), (1, NOT_DONE, skipped)); self.assertNotIn(READY[0], lines)
            lines, code = self.run_finish(bare, yes=True)
            self.assertEqual((code, lines[-2:], SKIPS(lines)), (0, READY, skipped))
        self.probe.assert_not_called()  # no OpenRouter key, or yes
        lines, code = self.run_finish({"workspaces": {"default": {"openrouter": "sk-or-test"}}, "typesafe": "ts-test"})
        self.assertEqual((code, lines[-1], SKIPS(lines)), (1, NOT_DONE, ["skipped linear"]))

    def test_probe_failure_and_missing_claude(self):
        self.probe.return_value = (False, ["provider: no endpoints", "make the preset"])
        lines, code = self.run_finish(ALL)
        self.assertEqual(code, 1); self.assertIn("provider: no endpoints", lines); self.assertNotIn(READY[0], lines)
        self.claude = False
        lines, code = self.run_finish(ALL, yes=True)
        self.assertEqual((code, lines[-1], self.probe.call_count), (1, CLAUDE, 1))  # yes skips the probe


EXPORT = 'export PATH="$HOME/.local/bin:$PATH"'
PATH_LINES = ["~/.local/bin is not on your PATH; add this line to your shell profile:", EXPORT]
ROWS = [(n, lambda c: (True, ""), "true", "required", False, m) for n, m in
        [("apple", "run"), ("berry", "manual"), ("cherry", "run"), ("date", "run"), ("elder", "run"), ("fig", "run"), ("grape", "run"), ("kiwi", "key"), ("lime", "key")]]
NAMES = [r[0] for r in ROWS]

class Outcome(unittest.TestCase):
    def setUp(self):
        Finish.setUp(self)
        p = mock.patch.object(F.fc_steps, "STEPS", tuple(ROWS)); p.start(); self.addCleanup(p.stop)
        self.auth.write_text(json.dumps(ALL))

    def named(self, line, prefix):
        self.assertTrue(line.startswith(prefix), line)
        return sorted((n for n in NAMES if n in line), key=line.find)

    def test_groups_in_steps_order_then_herdr_then_path_then_the_old_lines(self):
        F.finish([("elder", "ok")], False); tail, code = F.finish([("elder", "ok")], False)  # second call: models already merged
        self.assertEqual(tail[-2:], READY)
        self.assertFalse(any(l.startswith(("failed", "waiting", "run by hand", "skipped:", "~/")) for l in tail))
        self.herdr.reset_mock(); self.herdr.return_value, self.path = ("written", ["herdr: wrote config.toml"]), EXPORT
        results = [("fig", "failed"), ("lime", "failed"), ("cherry", "claude"), ("grape", "done"), ("apple", "failed"),
                   ("kiwi", "skipped"), ("berry", "manual"), ("date", "skipped"), ("elder", "ok")]
        lines, code2 = F.finish(results, False)
        self.assertEqual([self.named(l, p) for l, p in zip(lines, ["failed: ", "waiting on Claude Code: ", "run by hand: ", "skipped: "])],
                         [["apple", "fig"], ["cherry"], ["berry"], ["date"]])
        self.assertEqual((lines[4:], code2), (["herdr: wrote config.toml", *PATH_LINES, *tail], code))
        home, checkout = Path(os.environ["HOME"]), Path(F.__file__).resolve().parents[1]
        self.herdr.assert_called_once()
        self.assertEqual([str(a) for a in self.herdr.call_args.args], [str(home / ".config/herdr/config.toml"), str(checkout / "setup/herdr.toml")])

    def test_symlinked_config_gets_manual_lines_and_nothing_else_is_added(self):
        F.finish([], False); quiet, _ = F.finish([], False)
        self.herdr.return_value = ("manual", ["set by hand in config.toml: a = 1", "b = 2"])
        lines, _ = F.finish([("apple", "done"), ("kiwi", "failed"), ("lime", "skipped")], False)
        self.assertEqual(lines, ["set by hand in config.toml: a = 1", "b = 2", *quiet])
        self.assertEqual(self.herdr.call_count, 3)  # once per call
        self.path = EXPORT; lines, code = F.finish([("berry", "manual")], True)
        self.assertEqual((self.named(lines[0], "run by hand: "), lines[1:5], code),
                         (["berry"], ["set by hand in config.toml: a = 1", "b = 2", *PATH_LINES], 0))


ADDED, WHY = "added default models to ~/.compose/config.json: ", "provider: no endpoints for glm-5-3-flash-fast"
NOT_DONE_LINE = lambda lines: [l for l in lines if l.startswith(NOT_DONE)]
REAL_PROBE = F.fc_defaults.probe_implementer

class Tidy(unittest.TestCase):
    run_finish = Finish.run_finish

    def setUp(self):
        Finish.setUp(self); self.why = (True, "ok")
        for p in (mock.patch.object(F.fc_defaults, "probe_implementer", REAL_PROBE),
                  mock.patch.object(F.fc_defaults.fc_models, "model_available", lambda m: self.why)):
            p.start(); self.addCleanup(p.stop)

    def test_preset_steps_once_in_every_result(self):
        self.assertTrue(F.fc_defaults.PRESET_STEPS)
        for self.why, auth, yes in (((True, "ok"), ALL, False), ((False, WHY), ALL, False), ((False, WHY), ALL, True),
                                    ((False, WHY), {"workspaces": {"default": {}}}, False)):
            lines, _ = self.run_finish(auth, yes)
            self.assertEqual([lines.count(l) for l in F.fc_defaults.PRESET_STEPS], [1] * len(F.fc_defaults.PRESET_STEPS), lines)
            self.assertEqual(WHY in lines, not self.why[0] and auth is ALL and not yes)

    def test_models_in_one_line_and_no_write_when_nothing_to_add(self):
        crew = F.fc_defaults.DEFAULT_MODELS["crew"]
        self.cfg.write_text(json.dumps({"models": {"implementer": "pi:mine", "crew": {}}}))
        lines, code = self.run_finish(ALL)
        self.assertEqual(([l for l in lines if "models" in l and l not in F.fc_defaults.PRESET_STEPS], code),
                         ([f"{ADDED}fallback, crew ({len(crew)} roles)"], 0))
        self.cfg.write_text(json.dumps({"models": {"implementer": "pi:mine", "crew": crew}}))
        self.assertIn(ADDED + "fallback", self.run_finish(ALL)[0])
        self.cfg.unlink(); lines, _ = self.run_finish(ALL)  # fresh: no config.json yet
        added = [l for l in lines if l.startswith(ADDED)]
        self.assertEqual(len(added), 1); self.assertIn("implementer", added[0]); self.assertTrue(added[0].endswith(f"crew ({len(crew)} roles)"))
        self.assertFalse([l for l in lines if "{" in l or l.startswith("models.")])
        os.utime(self.cfg, ns=(10**18, 10**18)); before = (self.cfg.read_bytes(), self.cfg.stat().st_mtime_ns, self.cfg.stat().st_ino)
        lines, code = self.run_finish(ALL)
        self.assertEqual((self.cfg.read_bytes(), self.cfg.stat().st_mtime_ns, self.cfg.stat().st_ino, code), (*before, 0))
        self.assertFalse([l for l in lines if l.startswith("added default models")]); self.assertEqual(lines[-2:], READY)

    def test_not_finished_says_why(self):
        self.why = (False, WHY)
        lines, code = self.run_finish(ALL)
        self.assertEqual((lines[-1], code), (NOT_DONE + ": the model probe failed", 1))
        self.why = (True, "ok")
        for self.connected, auth, keys in ((False, {"workspaces": {"default": {}}}, ["openrouter", "typesafe", "linear"]),
                                           (True, {"workspaces": {"default": {"openrouter": "sk-or-test"}}}, ["typesafe"])):
            lines, code = self.run_finish(auth); (line,) = NOT_DONE_LINE(lines)
            self.assertEqual((lines[-1], code), (line, 1))
            self.assertTrue(line.startswith(NOT_DONE + ": missing ") and ";" not in line, line)
            self.assertEqual([k for k in ("openrouter", "typesafe", "linear") if k in line.lower()], keys)
        self.why = (False, WHY)
        (line,) = NOT_DONE_LINE(self.run_finish({"workspaces": {"default": {"openrouter": "sk-or-test"}}})[0])
        self.assertTrue(line.startswith(NOT_DONE + ": missing ") and line.endswith("; the model probe failed"), line)
        self.assertNotIn("openrouter", line.lower())
