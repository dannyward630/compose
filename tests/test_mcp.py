import subprocess, sys, unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import fc_mcp  # noqa: E402

P = ["claude_ai_Claude_Docs", "claude_ai_Google_Calendar", "claude_ai_Linear", "claude_ai_Notion", "frame0", "framelink-figma", "graft", "plugin_product-management_figma"]
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
        d = ("linear", "graft", "figma", "framelink-figma")
        for role, servers, skills in [("toolsmith", ("graft",), False), ("implementer", ("graft",), False),
                                      ("designer", d, True), ("design-003", d, True), ("design-review", d, True),
                                      ("planner", ("linear", "graft"), False), ("wayfinder", ("linear", "graft"), False),
                                      ("no-such-role", ("linear", "graft"), False)]:
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
        self.assertEqual(set(fc_mcp.disallowed("planner", P)), pat(*P) - pat("claude_ai_Linear", "graft"))
        for r in ("designer", "design-review"):
            self.assertEqual(set(fc_mcp.disallowed(r, P + ["claude_ai_Figma"])), pat(*P) - pat("claude_ai_Linear", "graft", "framelink-figma"))
        self.assertEqual(set(fc_mcp.disallowed("toolsmith", P)), pat(*P) - pat("graft"))
        self.assertEqual(set(fc_mcp.disallowed("wayfinder", P, frame0=True)), pat(*P) - pat("claude_ai_Linear", "graft", "frame0"))
        self.assertEqual(set(fc_mcp.disallowed("designer", ["LINEAR_x", "Graft2"])), set())


if __name__ == "__main__":
    unittest.main()
