import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_providers  # bin/ is on sys.path once compose.py is loaded

FAKE = {"base_url": "http://127.0.0.1:1/v1", "models": ["fake-1", "fake-2"]}

def cp_apply(test, cfg):
    """A scratch config.json holding `cfg`, fc_config pointed at it, and apply_config() run; every global it sets is restored."""
    c, d = fc.fc_config, Path(tempfile.mkdtemp()); (d / "config.json").write_text(json.dumps(cfg))
    for p in [mock.patch.object(c, "CONFIG_PATH", d / "config.json"), mock.patch.object(c, "AUTH_PATH", d / "auth.json"), mock.patch.object(c, "ENV_FILE", d / ".env"),
              mock.patch.object(c, "PROBE_CACHE", d / "model-probe.json"), mock.patch.dict(os.environ), mock.patch.object(c, "PROVIDERS", {})] + [
              mock.patch.object(c, k, getattr(c, k)) for k in ("DEFAULT_MODEL", "FALLBACK_MODEL", "TEST_READER", "CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK")]:
        p.start(); test.addCleanup(p.stop)
    c.apply_config()

class ConfigProviders(unittest.TestCase):
    def exits(self, cfg, line):
        with self.assertRaises(SystemExit) as e: cp_apply(self, cfg)
        self.assertEqual(str(e.exception.code), f"{fc.fc_config.CONFIG_PATH}: {line}")
    def test_provider_of_names_declared_providers_only(self):
        cp_apply(self, {"providers": {"fakelocal": FAKE}})
        for m in ("pi:fakelocal/fake-1", "fakelocal/fake-1"): self.assertEqual(fc.fc_config.provider_of(m), ("fakelocal", "fake-1"))
        self.assertEqual(fc.fc_config.provider_of("pi:fakelocal/org/m"), ("fakelocal", "org/m"))
        for m in ("claude:opus", "pi:openrouter/x/y", "other/fake-1", "pi:other/x", "fakelocal", "pi:fakelocal"): self.assertIsNone(fc.fc_config.provider_of(m), m)
    def test_workspace_provider_replaces_the_top_level_one_by_name(self):
        other = {"base_url": "http://h/v1"}
        cp_apply(self, {"workspace": "w", "providers": {"fakelocal": FAKE, "other": other}, "workspaces": {"w": {"providers": {"fakelocal": {"base_url": "https://ws/v1"}}}}})
        self.assertEqual(fc.fc_config.PROVIDERS, {"fakelocal": {"base_url": "https://ws/v1"}, "other": other})
    def test_bad_entries_exit_with_their_line(self):
        for name in ("Fake", "-x", "_x", "a b", "a/b", ""):
            with self.subTest(name): self.exits({"providers": {name: FAKE}}, f"provider names are lowercase letters, digits, - and _: {name!r}")
        for name in ("openrouter", "openrouter-fast"):
            with self.subTest(name): self.exits({"providers": {name: {}}}, f"providers.{name} is reserved: openrouter models already route there")
        for entry in ({"models": ["a"]}, {"base_url": ""}, {"base_url": "localhost:11434/v1"}, {"base_url": "ftp://h/v1"}):
            with self.subTest(entry): self.exits({"providers": {"fakelocal": entry}}, "providers.fakelocal needs a base_url such as http://localhost:11434/v1")
        for models in ("fake-1", [1], {"a": "b"}, ["a", None]):
            with self.subTest(models): self.exits({"providers": {"fakelocal": {"base_url": "http://h/v1", "models": models}}}, "providers.fakelocal.models must be a list of model ids")
        self.exits({"providers": {"first": {"base_url": "nope"}, "Bad": FAKE}}, "providers.first needs a base_url such as http://localhost:11434/v1")
    def test_configured_model_missing_from_models_exits(self):
        bad, line = "fakelocal/nope", "{} is not in providers.fakelocal.models: fake-1, fake-2"
        self.exits({"providers": {"fakelocal": FAKE}, "models": {"implementer": "pi:" + bad}}, line.format("pi:" + bad))
        for models in ({"fallback": bad}, {"fix": bad}, {"test_reader": bad}, {"crew": {"s": bad}}, {"crew": {"s": {"model": bad}}},
                       {"crew": {"s": {"model": "claude:opus", "fallback": bad}}}, {"crew": {"s": {"model": "claude:opus", "fallback": ["claude:haiku", {"model": bad}]}}}):
            with self.subTest(models): self.exits({"providers": {"fakelocal": FAKE}, "models": models}, line.format(bad))
    def test_unrestricted_models_pass_and_no_providers_leaves_other_settings(self):
        cp_apply(self, {"models": {"implementer": "claude:opus"}})
        self.assertEqual((fc.fc_config.PROVIDERS, fc.fc_config.DEFAULT_MODEL), ({}, "claude:opus"))
        models = {"implementer": "pi:fakelocal/fake-2", "fallback": "pi:open/any/id", "test_reader": "claude:opus", "crew": {"small": "fakelocal/fake-1"}}
        cp_apply(self, {"providers": {"fakelocal": FAKE, "open": {"base_url": "http://h/v1"}}, "models": models})
        self.assertEqual(fc.fc_config.DEFAULT_MODEL, "pi:fakelocal/fake-2")

PE_JS = """// generated by compose from ~/.compose/config.json providers; do not edit
const PROVIDERS = <json>;
export default function (pi) {
  const want = process.env.COMPOSE_PI_MODEL || "";
  for (const p of PROVIDERS) {
    const ids = p.models.length ? p.models : want.startsWith(p.name + "/") ? [want.slice(p.name.length + 1)] : [];
    pi.registerProvider(p.name, { name: p.name, baseUrl: p.baseUrl, apiKey: p.apiKeyEnv ? process.env[p.apiKeyEnv] || "" : "none", api: "openai-completions",
      models: ids.map((id) => ({ id, name: id, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 131072, maxTokens: 16384 })) });
  }
}
"""

def pe_provider_of(model):
    name, _, mid = model.removeprefix("pi:").partition("/")
    return (name, mid) if name == "fakelocal" and mid else None

class PiExtension(unittest.TestCase):
    def setUp(self):
        self.d, self.providers = Path(tempfile.mkdtemp()), {"fakelocal": {"base_url": "http://127.0.0.1:1/v1", "models": ["fake-1"]}}
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", self.d / "config.json"), mock.patch.object(fc.fc_config, "PROVIDERS", self.providers),
                  mock.patch.object(fc.fc_config, "provider_of", pe_provider_of)):
            p.start(); self.addCleanup(p.stop)
        self.js = self.d / "pi-providers.js"
    def test_text_is_the_template_with_the_providers_json(self):
        self.providers["other"] = {"base_url": "http://h/v1"}  # no models: an empty list; sorted by name
        rows = [{"apiKeyEnv": None, "baseUrl": p["base_url"], "models": p.get("models", []), "name": n} for n, p in sorted(self.providers.items())]
        self.assertEqual(fc_providers.pi_extension_text().rstrip("\n"), PE_JS.replace("<json>", json.dumps(rows, sort_keys=True)).rstrip("\n"))
    def test_args_write_the_file_only_when_providers_change(self):
        for m in ("pi:fakelocal/fake-1", "pi:fakelocal/org/m"): self.assertEqual(fc_providers.pi_args(m), ["-e", str(self.js)])
        self.assertEqual(self.js.read_text(), fc_providers.pi_extension_text())
        os.utime(self.js, ns=(1, 1)); fc_providers.pi_args("pi:fakelocal/fake-1")
        self.assertEqual(self.js.stat().st_mtime_ns, 1)
        self.providers["fakelocal"]["base_url"] = "http://127.0.0.1:2/v1"; fc_providers.pi_args("pi:fakelocal/fake-1")
        self.assertIn("http://127.0.0.1:2/v1", self.js.read_text())
    def test_other_models_get_nothing_and_write_nothing(self):
        for m in ("claude:opus", "pi:openrouter/x/y", "pi:undeclared/x", "undeclared/x"):
            with self.subTest(m): self.assertEqual((fc_providers.pi_args(m), fc_providers.pi_env(m)), ([], {}))
        self.assertFalse(self.js.exists())
    def test_env_names_the_provider_and_id(self):
        for m, want in (("pi:fakelocal/fake-1", "fakelocal/fake-1"), ("fakelocal/fake-1", "fakelocal/fake-1"), ("pi:fakelocal/org/m", "fakelocal/org/m")):
            self.assertEqual(fc_providers.pi_env(m), {"COMPOSE_PI_MODEL": want})
    def test_cost_is_priced_then_free_when_local_then_the_reported_one(self):
        u = {"tokens_in": 1000, "tokens_out": 2000, "cost": 9.0}
        self.assertEqual(fc_providers.cost("openrouter/openai/gpt-oss-120b", u), (1000 * 0.35 + 2000 * 0.75) / 1e6)
        self.assertEqual(fc_providers.cost("pi:fakelocal/fake-1", u), 0.0)
        with mock.patch.object(fc.fc_config, "PRICES", {"fakelocal/fake-1": (1, 2)}): self.assertEqual(fc_providers.cost("fakelocal/fake-1", u), 5000 / 1e6)
        self.assertEqual(fc_providers.cost("claude:opus", u), 9.0)
        self.assertIsNone(fc_providers.cost("claude:opus", {"tokens_in": 1, "tokens_out": 2}))
