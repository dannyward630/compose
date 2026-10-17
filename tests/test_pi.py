import importlib, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_pi as pi  # noqa: E402

MODEL = "z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast"


class PiChecks(unittest.TestCase):
    """The read side of pi's openrouter-fast provider, the TEXT_MODEL lines, and pi's own auth.json overrides."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def file(self, text, name="f.json"):
        (self.dir / name).write_text(text if isinstance(text, str) else json.dumps(text))
        return self.dir / name

    def test_provider_declared(self):
        self.assertEqual(pi.PROVIDER["models"][0]["id"], MODEL)
        self.assertEqual((pi.PROVIDER["apiKey"], pi.PROVIDER["baseUrl"]), ("$OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"))
        self.assertEqual(pi.TEXT_MODEL_DEFAULTS, {"TEXT_MODEL": "inception/mercury-2.5", "TEXT_MODEL_BASE_URL": "https://openrouter.ai/api/v1"})
        other = {"anthropic": {"models": [{"id": "claude"}]}}
        self.assertTrue(pi.provider_declared(self.file({"providers": {**other, "openrouter-fast": {"models": [{"id": "x"}, {"id": MODEL}]}}})))
        for bad in ({"providers": other}, {"providers": {"openrouter-fast": {"models": [{"id": "x"}]}}},
                    {"providers": {"openrouter": {"models": [{"id": MODEL}]}}}, {"providers": {"openrouter-fast": {}}}, "{not json", "[]"):
            self.assertFalse(pi.provider_declared(self.file(bad)), bad)
        self.assertFalse(pi.provider_declared(self.dir / "missing.json"))

    def test_text_model_set(self):
        both = "A=1\nTEXT_MODEL=some/model\nTEXT_MODEL_BASE_URL=http://x\n"
        self.assertTrue(pi.text_model_set(self.file(both, ".env")))
        for bad in ("TEXT_MODEL=a\n", "TEXT_MODEL_BASE_URL=b\n", "A=1\n", "TEXT_MODEL=\nTEXT_MODEL_BASE_URL=b\n", "TEXT_MODEL_API_KEY=k\nTEXT_MODEL_BASE_URL=b\n"):
            self.assertFalse(pi.text_model_set(self.file(bad, ".env")), bad)
        self.assertFalse(pi.text_model_set(self.dir / "none.env"))

    def test_pi_auth_overrides(self):
        o = pi.pi_auth_overrides
        key = {"type": "api_key", "key": "sk-or-test"}
        self.assertEqual(o(self.file({"openrouter-fast": key, "anthropic": key, "openrouter": key})), ["openrouter", "openrouter-fast"])
        self.assertEqual(o(self.file({"openrouter-fast": key})), ["openrouter-fast"])
        self.assertEqual(o(self.file({"anthropic": {"openrouter": key}})), [])
        self.assertEqual(o(self.file("{oops")), [])
        self.assertEqual(o(self.dir / "missing.json"), [])

    def test_paths_follow_agent_dir(self):
        self.addCleanup(importlib.reload, pi)
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(self.dir)}):
            importlib.reload(pi)
        self.assertEqual((pi.PI_MODELS, pi.PI_AUTH), (self.dir / "models.json", self.dir / "auth.json"))
        with mock.patch.dict(os.environ, {"HOME": str(self.dir)}):
            os.environ.pop("PI_CODING_AGENT_DIR", None)
            importlib.reload(pi)
        self.assertEqual(pi.PI_MODELS, self.dir / ".pi" / "agent" / "models.json")

