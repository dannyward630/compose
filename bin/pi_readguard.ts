// pi extension: asks compose's read guard (bin/fc_readguard.py) before each tool call. COMPOSE_READGUARD is the shell line
// that runs the guard; a non-empty reply blocks the call with that reply as the reason.
import { spawnSync } from "node:child_process";

export default function (pi: any) {
  pi.on("tool_call", (event: any) => {
    const cmd = process.env.COMPOSE_READGUARD;
    if (!cmd) return;
    const r = spawnSync("sh", ["-c", cmd], {
      input: JSON.stringify({ tool: event.toolName, args: event.input }),
      encoding: "utf8",
    });
    if (r.error || r.status !== 0) {
      return { block: true, reason: (r.stderr || r.error?.message || `sh ${r.signal ?? r.status}`).trim() };
    }
    const reply = r.stdout.trim();
    if (reply) return { block: true, reason: reply };
  });
}
