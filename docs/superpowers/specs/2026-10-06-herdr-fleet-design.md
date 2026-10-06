# fast-coding on herdr: a steerable fleet

Date: 2026-10-06. Status: approved in conversation, implementation follows.

## Destination

When fast-coding runs inside herdr, the captain sees the whole feature in herdr's sidebar without asking the orchestrator:
one space per project, one tab per task, one named agent per implementer, each with a live state and a readable title.
The orchestrator steers those agents with text through herdr instead of waiting for the CLI to exhaust attempts.
Outside herdr nothing changes.

## Detection

The CLI and the skill are inside herdr when `HERDR_ENV=1` and `HERDR_SOCKET_PATH`, `HERDR_PANE_ID`, `HERDR_WORKSPACE_ID` are set.
That is herdr's own contract and what its skill checks.
The orchestrator's harness is read from `herdr agent get $HERDR_PANE_ID` (`agent` field, `claude`, `pi`, ...), confirmed by `CLAUDECODE=1` for Claude Code.
The skill invokes the `herdr` skill when inside herdr, so herdr's safety rules apply without restating them.

## Topology and names

| herdr object | fast-coding object | label |
|---|---|---|
| space (workspace) | one project | `<slug>`, opened with `herdr worktree open --path ../fast-coding-<slug> --label <slug>` so it is grouped under the repo's space |
| tab `status` | the project | runs `fast-coding status --project <slug> --watch` |
| tab per task | one task | `NNN <title>` |
| agent in that tab's pane | the task's implementer (pi) | `<slug>-NNN`, trimmed to herdr's 32-char limit, `[a-z][a-z0-9_-]` |
| tab `verify` | one verify run | one pane per stage (`checks`, `review`, `jev`) and per e2e case, reported with `pane report-agent --source fast-coding` |
| orchestrator's own pane | the orchestrator | renamed `<slug> orchestrator`; it stays where the captain started it |

Pane metadata (`pane report-metadata`, source `fast-coding`) carries `--title "NNN <title>"`, state labels `working=attempt N/3`, `idle=passed`, `blocked=failed`, and tokens `model`, `cost`.

Tabs stay after a run so the captain can read them. `clean` closes the project's space once the project is fully merged.

## Execution: implementers become herdr agents

`implementer()` is the seam where pi, OpenCode, and Claude are already swappable; it returns `(session, text, tool_calls, usage)`.
A fourth backend, `herdr_pi`, is selected automatically for `pi:` models when inside herdr:

1. First call for a task: `herdr tab create --workspace <space> --label "NNN <title>" --cwd <clone> --no-focus`, then
   `herdr agent start <slug>-NNN --kind pi --pane <root_pane> -- --session-id <uuid> --session-dir <dir> --no-extensions ... --model <model>`.
   pi runs interactively, in `--tui-mode regular`, with the herdr pi extension loaded explicitly (`-e ~/.pi/agent/extensions/herdr-agent-state.ts`) so it reports its own state.
2. Every call: `herdr agent prompt <name> "<prompt>" --wait --timeout <ms>`; on return, usage is read from the pi session file (per-turn `usage` records with `input`, `output`, `cacheRead`, `cacheWrite`, `reasoning`, `cost.total`), diffed against the previous read.
3. The guard loop in `run_task` is unchanged: test, 350-line budget, no documents, `files:` allowlist, protected files. A failed guard is the next `agent prompt` to the same agent, which is the same steering channel the orchestrator uses.
4. When the task ends (passed, failed, or payment halt) the agent is left in place, idle, so the captain or the orchestrator can read it or steer it; `clean` closes it with the space.

`agent prompt --wait` returns on `idle`, `done`, or `blocked`.
`blocked` means pi is asking something; the CLI reads the pane (`agent read`) into the result log, reports the task as blocked, and the orchestrator decides.

Headless pi, OpenCode, and Claude backends are untouched and remain the path outside herdr and for non-pi tasks.

## Steering from the skill

While `run` executes, the orchestrator runs it in the background and watches `herdr agent list` for the project's agents.
A `blocked` agent, or one `working` with no output change for a few minutes, is read with `agent read --source recent-unwrapped --lines 80` and nudged with `agent prompt <name> "<one specific instruction>"`.
The nudge is logged as a comment on the task's Linear issue.
The orchestrator never edits product code; it writes tests, tasks, tickets, and steers.
Status is a wake event, not truth: decisions come from `fast-coding status`, `results/NNN.json`, and the diff.

## Not in this round

OpenCode and Claude implementers as herdr agents (same backend shape, later).
A durable inbox and watcher daemon (firstmate's `fm-send`/`fm-watch`); herdr's `agent wait --until blocked` covers it until steering must survive restarts.
Remote machines (`--machine`).
