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
