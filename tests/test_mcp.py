import hermetic  # first: no test sees the real home
import os, subprocess, sys, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import fc_mcp  # noqa: E402

P = ["claude_ai_Claude_Docs", "claude_ai_Google_Calendar", "claude_ai_Linear", "claude_ai_Notion", "frame0", "framelink-figma", "graft", "plugin_product-management_figma", "trail"]
LIST = """Checking MCP server health…

claude.ai Linear: https://mcp.linear.app/mcp (HTTP) - ✔ Connected
plugin:product-management:google calendar: https://x - Not configured
frame0: npx -y frame0-mcp-server - ✗ Failed to connect: spawn npx ENOENT
graft: graft mcp - ✔ Connected

MCP config diagnostics ⚠

[Conflicting scopes]
├ Server "frame0" is defined in multiple scopes: user (npx), local (npx --api-port=1).
"""


def pat(*names):
    return {"mcp__%s__*" % n for n in names}


class RoleMcp(unittest.TestCase):
    def test_servers_and_skills_by_role(self):
        d = ("linear", "figma", "framelink-figma")
        for role, servers, skills in [("toolsmith", (), False), ("implementer", (), False),
                                      ("designer", d, True), ("design-003", d, True), ("design-review", d, True),
                                      ("planner", ("linear",), False), ("wayfinder", ("linear",), False),
                                      ("no-such-role", ("linear",), False)]:
            self.assertEqual((tuple(fc_mcp.servers_for(role)), fc_mcp.keeps_skills(role)), (servers, skills), role)

    def test_installed_servers_reads_list_in_cwd(self):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, LIST, "")) as run:
            got = fc_mcp.installed_servers("/some/worktree")
        self.assertEqual(got, ["claude_ai_Linear", "plugin_product-management_google_calendar", "frame0", "graft"])
        self.assertEqual(list(run.call_args.args[0]), ["claude", "mcp", "list"])
        self.assertEqual(str(run.call_args.kwargs["cwd"]), "/some/worktree")

    def test_installed_servers_empty_on_failure(self):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, LIST, "")):
            self.assertEqual(fc_mcp.installed_servers("/w"), [])
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("claude")):
            self.assertEqual(fc_mcp.installed_servers("/w"), [])

    def test_disallowed(self):
        self.assertEqual(set(fc_mcp.disallowed("planner", P)), pat(*P) - pat("claude_ai_Linear"))
        for r, s in [(r, s) for r in ("designer", "design-review", "design-003") for s in (P, P + ["claude_ai_Figma"])]:
            self.assertEqual(set(fc_mcp.disallowed(r, s)), pat(*P) - pat("claude_ai_Linear", "framelink-figma"))
        for r in ("toolsmith", "implementer", "no-such-role", "orchestrator"):  # graft and trail are denied for every role
            self.assertLessEqual(pat("graft", "trail"), set(fc_mcp.disallowed(r, P)), r)
        self.assertEqual(set(fc_mcp.disallowed("toolsmith", P)), pat(*P))
        self.assertEqual(set(fc_mcp.disallowed("wayfinder", P, frame0=True)), pat(*P) - pat("claude_ai_Linear", "frame0"))
        self.assertEqual(set(fc_mcp.disallowed("designer", ["LINEAR_x", "Graft2"])), pat("LINEAR_x", "Graft2"))

    def test_no_mcpjson_approval_is_left(self):
        self.assertFalse(hasattr(fc_mcp, "wired_mcpjson"))
        self.assertFalse(hasattr(fc_mcp, "GRAFT_MCPJSON"))


if __name__ == "__main__":
    unittest.main()
