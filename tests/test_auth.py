import hermetic  # first: no test sees the real home
import json, os, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_auth, fc_core


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class AuthStore(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "store" / "auth.json"

    def test_read_missing_and_present(self):
        self.assertEqual(fc_auth.read_auth(self.path), {})
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"typesafe": "ts-test"}))
        self.assertEqual(fc_auth.read_auth(self.path), {"typesafe": "ts-test"})

    def test_write_is_atomic_and_private(self):
        data = {"workspaces": {"default": {"openrouter": "sk-or-test"}}}
        with mock.patch.object(fc_core, "atomic_write", wraps=fc_core.atomic_write) as aw:
            fc_auth.write_auth(self.path, data)
        aw.assert_called()
        self.assertEqual(json.loads(self.path.read_text()), data)
        self.assertEqual((mode(self.path), mode(self.path.parent)), (0o600, 0o700))

    def test_write_tightens_existing_directory(self):
        self.path.parent.mkdir()
        os.chmod(self.path.parent, 0o755)
        self.path.write_text("{}")
        os.chmod(self.path, 0o644)
        fc_auth.write_auth(self.path, {"typesafe": "ts-test"})
        self.assertEqual((mode(self.path), mode(self.path.parent)), (0o600, 0o700))

    def test_workspace_key_falls_back_to_default(self):
        auth = {"workspaces": {"default": {"openrouter": "sk-or-default", "linear": "lin-default"},
                               "acme": {"openrouter": "sk-or-acme"}}, "typesafe": "ts-test"}
        key = fc_auth.workspace_key
        self.assertEqual(key(auth, "acme", "openrouter"), "sk-or-acme")
        self.assertEqual(key(auth, "acme", "linear"), "lin-default")
        self.assertEqual(key(auth, "other", "openrouter"), "sk-or-default")
        self.assertEqual(key(auth, "acme", "typesafe"), "ts-test")
        self.assertIsNone(key({"workspaces": {"acme": {"openrouter": "sk-or-acme"}}}, "other", "openrouter"))
        self.assertIsNone(key({}, "default", "typesafe"))

    def test_set_key_keeps_other_entries(self):
        fc_auth.set_key(self.path, "default", "openrouter", "sk-or-old")
        self.assertEqual((mode(self.path), mode(self.path.parent)), (0o600, 0o700))
        fc_auth.set_key(self.path, "default", "linear", "lin-test")
        fc_auth.set_key(self.path, "acme", "openrouter", "sk-or-acme")
        fc_auth.set_key(self.path, "acme", "typesafe", "ts-test")
        fc_auth.set_key(self.path, "default", "openrouter", "sk-or-new")
        self.assertEqual(json.loads(self.path.read_text()), {
            "workspaces": {"default": {"openrouter": "sk-or-new", "linear": "lin-test"}, "acme": {"openrouter": "sk-or-acme"}},
            "typesafe": "ts-test"})


VALUES = ("sk-or-top", "lin-top", "sk-or-work", "ts-cfg", "sk-or-env", "sk-or-auth", "ts-env")
MODELS = {"implementer": "pi:x/y"}
ENV = "# keys\nTYPESAFE_API_KEY=ts-env\nTEXT_MODEL=pi:x/y\nTEXT_MODEL_API_KEY=sk-or-env\nTAIL=1\n"


class KeyMove(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        d = Path(t.name)
        self.cfg, self.env, self.auth = d / "config.json", d / ".env", d / "auth.json"

    def write(self, cfg=None, env=None, auth=None):
        for path, data in ((self.cfg, cfg), (self.auth, auth)):
            if data is not None: path.write_text(json.dumps(data))
        if env is not None: self.env.write_text(env)

    def test_moves_every_old_place_once(self):
        self.write({"workspace": "work", "openrouter_api_key": "sk-or-top", "linear_api_key": "lin-top", "models": MODELS,
                    "env": {"TYPESAFE_API_KEY": "ts-cfg", "OTHER": "x"},
                    "workspaces": {"work": {"openrouter_api_key": "sk-or-work", "linear_api_key": "", "models": MODELS}}},
                   ENV.replace("TYPESAFE_API_KEY=ts-env\n", ""), {"workspaces": {"work": {"openrouter": "sk-or-auth"}}})
        before = fc_auth.old_keys(self.cfg, self.env)
        self.assertEqual(sorted(before), sorted([(n, self.cfg) for n in ("openrouter_api_key", "linear_api_key", "env.TYPESAFE_API_KEY",
                         "workspaces.work.openrouter_api_key", "workspaces.work.linear_api_key")] + [("TEXT_MODEL_API_KEY", self.env)]))
        lines = fc_auth.move_keys(self.cfg, self.env, self.auth)
        self.assertEqual(len(lines), 6)
        self.assertEqual(sum("config.json" in l for l in lines), 5)
        self.assertEqual(sum(".env" in l for l in lines), 1)
        self.assertFalse([v for v in VALUES for l in lines if v in l])
        self.assertEqual(json.loads(self.auth.read_text()), {"typesafe": "ts-cfg", "workspaces": {
            "default": {"openrouter": "sk-or-top", "linear": "lin-top"}, "work": {"openrouter": "sk-or-auth", "linear": ""}}})
        self.assertEqual(json.loads(self.cfg.read_text()), {"workspace": "work", "models": MODELS, "env": {"OTHER": "x"},
                                                            "workspaces": {"work": {"models": MODELS}}})
        self.assertEqual(self.cfg.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.env.read_text(), "# keys\nTEXT_MODEL=pi:x/y\nTAIL=1\n")
        self.assertEqual(fc_auth.old_keys(self.cfg, self.env), [])
        snap = [p.read_bytes() for p in (self.cfg, self.env, self.auth)]
        self.assertEqual(fc_auth.move_keys(self.cfg, self.env, self.auth), [])
        self.assertEqual([p.read_bytes() for p in (self.cfg, self.env, self.auth)], snap)

    def test_env_file_alone_and_missing_files(self):
        self.assertEqual(fc_auth.old_keys(self.cfg, self.env), [])
        self.assertEqual(fc_auth.move_keys(self.cfg, self.env, self.auth), [])
        self.write(env=ENV)
        lines = fc_auth.move_keys(self.cfg, self.env, self.auth)
        self.assertEqual(len(lines), 2)
        self.assertFalse([v for v in VALUES for l in lines if v in l])
        self.assertEqual(json.loads(self.auth.read_text()), {"typesafe": "ts-env", "workspaces": {"default": {"openrouter": "sk-or-env"}}})
        self.assertEqual(self.env.read_text(), "# keys\nTEXT_MODEL=pi:x/y\nTAIL=1\n")
        self.assertFalse(self.cfg.exists())


class KeyClash(unittest.TestCase):
    def setUp(self):
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cfg, self.env, self.auth = d / "config.json", d / ".env", d / "auth.json"

    def move(self, cfg, env, auth=None):
        self.cfg.write_text(json.dumps(cfg))
        self.env.write_text(env)
        if auth: self.auth.write_text(json.dumps(auth))
        lines = fc_auth.move_keys(self.cfg, self.env, self.auth)
        self.assertFalse([l for l in lines for v in ("sk-or", "lin-", "ts-") if v in l])
        return sorted(lines)

    def out(self, *names):
        return sorted(f"{n} out of {self.env if n.isupper() else self.cfg}" for n in names)

    def test_differing_keys_keep_the_first_and_leave_the_other(self):
        env = "A=1\nTYPESAFE_API_KEY=ts-env\nTEXT_MODEL_API_KEY=sk-or-env\n"
        lines = self.move({"openrouter_api_key": "sk-or-cfg", "env": {"TYPESAFE_API_KEY": "ts-cfg"}}, env)
        self.assertEqual(lines, self.out("openrouter_api_key", "env.TYPESAFE_API_KEY"))
        self.assertEqual(json.loads(self.auth.read_text()), {"workspaces": {"default": {"openrouter": "sk-or-cfg"}}, "typesafe": "ts-cfg"})
        self.assertEqual(self.env.read_text(), env)
        self.assertEqual(sorted(fc_auth.old_keys(self.cfg, self.env)), [("TEXT_MODEL_API_KEY", self.env), ("TYPESAFE_API_KEY", self.env)])
        snap = [p.read_bytes() for p in (self.cfg, self.env, self.auth)]
        self.assertEqual(fc_auth.move_keys(self.cfg, self.env, self.auth), [])
        self.assertEqual([p.read_bytes() for p in (self.cfg, self.env, self.auth)], snap)

    def test_old_key_against_auth_json_per_slot(self):
        auth = {"workspaces": {"default": {"openrouter": "sk-or-auth"}, "work": {"linear": "lin-auth"}}, "typesafe": "ts-auth"}
        cfg = {"linear_api_key": "lin-top", "env": {"TYPESAFE_API_KEY": "ts-auth"},
               "workspaces": {"work": {"openrouter_api_key": "sk-or-work", "linear_api_key": "lin-other"}}}
        lines = self.move(cfg, "TEXT_MODEL_API_KEY=sk-or-auth\nTYPESAFE_API_KEY=ts-other\n", auth)
        self.assertEqual(lines, self.out("linear_api_key", "env.TYPESAFE_API_KEY", "workspaces.work.openrouter_api_key", "TEXT_MODEL_API_KEY"))
        self.assertEqual(json.loads(self.auth.read_text()), {"typesafe": "ts-auth", "workspaces": {
            "default": {"openrouter": "sk-or-auth", "linear": "lin-top"}, "work": {"linear": "lin-auth", "openrouter": "sk-or-work"}}})
        self.assertEqual(json.loads(self.cfg.read_text())["workspaces"], {"work": {"linear_api_key": "lin-other"}})
        self.assertEqual(self.env.read_text(), "TYPESAFE_API_KEY=ts-other\n")
        self.assertEqual(sorted(fc_auth.old_keys(self.cfg, self.env)),
                         sorted([("workspaces.work.linear_api_key", self.cfg), ("TYPESAFE_API_KEY", self.env)]))

    def test_equal_keys_in_both_places_are_both_removed(self):
        lines = self.move({"openrouter_api_key": "sk-or-same", "env": {"TYPESAFE_API_KEY": "ts-same"}},
                          "TEXT_MODEL_API_KEY=sk-or-same\nTYPESAFE_API_KEY=ts-same\nTAIL=1\n")
        self.assertEqual(lines, self.out("openrouter_api_key", "env.TYPESAFE_API_KEY", "TEXT_MODEL_API_KEY", "TYPESAFE_API_KEY"))
        self.assertEqual(json.loads(self.auth.read_text()), {"workspaces": {"default": {"openrouter": "sk-or-same"}}, "typesafe": "ts-same"})
        self.assertEqual(self.env.read_text(), "TAIL=1\n")
        self.assertEqual(fc_auth.old_keys(self.cfg, self.env), [])
