import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
import os
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_finish as F
ALL = {"workspaces": {"default": {"openrouter": "sk-or-test", "linear": "lin-test"}}, "typesafe": "ts-test"}
READY, NOT_DONE = ["compose is ready", "next: run compose to open herdr"], "setup is not finished"
SKIPS = lambda lines: [l for l in lines if l.startswith("skipped")]
CLAUDE = "Claude Code is missing: install it with curl -fsSL https://claude.ai/install.sh | bash, log in, then run compose setup again"

class Finish(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp()); self.cfg, self.auth = tmp / "config.json", tmp / "auth.json"
        self.cfg.write_text(json.dumps({"workspaces": {"w": {"target": "x"}}, "models": {"implementer": "pi:mine"}}))
        self.probe, self.claude, self.connected = mock.Mock(return_value=(True, ["probe passed"])), True, False
        for p in (mock.patch.object(F.fc_config, "CONFIG_PATH", self.cfg), mock.patch.object(F.fc_config, "AUTH_PATH", self.auth),
                  mock.patch.object(F.fc_config, "ENV_FILE", tmp / ".env"), mock.patch.object(F.fc_steps, "FRAMELINK_ENV", tmp / "figma.env"),
                  mock.patch.object(F.fc_defaults, "probe_implementer", self.probe),
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
