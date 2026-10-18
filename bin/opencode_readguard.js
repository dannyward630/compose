// OpenCode plugin: asks compose's read guard (bin/fc_readguard.py) before each tool call. COMPOSE_READGUARD is the shell line
// that runs the guard; a non-empty reply is thrown, which refuses the call, and so is any failure to run the guard.
import { spawnSync } from "node:child_process";

export const ReadGuard = async (ctx) => ({
  "tool.execute.before": async (input, output) => {
    const guard = process.env.COMPOSE_READGUARD;
    if (!guard) return;
    const r = spawnSync("sh", ["-c", guard], {input: JSON.stringify({tool: input.tool, args: {file_path: output.args.filePath,
                                                              path: output.args.path, command: output.args.command}}),
                                              encoding: "utf8"});
    if (r.error) throw new Error(r.error.message);
    if (r.status !== 0) throw new Error((r.stderr || `sh exited ${r.status ?? "on signal " + r.signal}`).trim());
    const reply = (r.stdout || "").trim();
    if (reply) throw new Error(reply);
  },
});
