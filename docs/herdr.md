# Running inside herdr

Inside [herdr](https://herdr.dev) the fleet is visible and steerable.
Outside it, the same commands run headless in one session.

## Roles

You are the captain.
The roles follow [firstmate](https://github.com/kunchenguid/firstmate).

| Role | Who | Where |
|---|---|---|
| first mate | the Claude session you started; creates the project, then only relays | the pane you started it in |
| orchestrator | runs the project from wayfinder to a verified stack | tab `orchestrator`, agent `<slug>-orchestrator` |
| crew | explore, wayfinder, groundwork, test writers, helpers, implementers | one tab each in the project's space |

The first mate and the orchestrator write no code.
For the orchestrator this is enforced: its tab is marked `FAST_CODING_ROLE=orchestrator`, and the plugin's PreToolUse hook (`fast-coding guard`) denies its edits except the CLI's JSON under `.fast-coding/`.

## Talking to the fleet

- You talk to the first mate; you can also type into any crew tab directly.
- Crews report up with `fast-coding report` (`working`, `needs-user`, `blocked`, `done`).
- A `needs-user` or `blocked` report pops a herdr notification and badges the pane `needs you`; nothing steals focus.
- `fast-coding crew focus --role <role>` jumps to a tab when you ask.

## Crew commands

```bash
fast-coding crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt
fast-coding explore --project <slug> | fast-coding crew start --project <slug> --role explore --title explore --brief -
fast-coding wayfinder --project <slug> --extra - < notes.md | fast-coding crew start --project <slug> --role wayfinder --title wayfinder --brief -
fast-coding crew list --project <slug>
fast-coding crew stop --project <slug> --role wayfinder   # refused until it reported done; --force overrides
fast-coding testcrews --project <slug>                    # one test-writing crew per task
fast-coding teardown --project <slug>                     # close finished tabs; the orchestrator's done runs it
```

Crew models come from the config per role; see [workspaces.md](workspaces.md#crew-models).

## Layout

| herdr | fast-coding | Label |
|---|---|---|
| space | one project | `<slug>` |
| tab | live `fast-coding status --watch` | `status` |
| tab | every implementer, one pane per task | `implementers` |
| pane | one task's interactive pi session | `NNN <title>`, agent `<slug>-NNN` |
| tab | the latest verify run, one pane per stage | `verify` |
| tab | the orchestrator | `orchestrator` |
| tab | one crew session | its title, agent `<slug>-<role>` |

Task panes show state (`attempt 2/3`, `passed`), model, and cost.
The orchestrator steers a working or blocked implementer with `herdr agent prompt <slug>-NNN "..."`, which lands in the same pi session the CLI drives.
`clean` closes the project's space with its worktree.

## Supervision

`fast-coding watch --project <slug>` sleeps until a task finishes, an agent blocks, a crew reports, a run ends, or verify finishes.
It prints one `event ...` line and exits, so a waiting orchestrator spends no tokens.
`--from orchestrator` makes the first mate wake only on the orchestrator's reports.
A run left silent with work pending raises a stall event after 240 s (`stall_seconds` in `verify.json`, or `watch --stall`).

Each watcher remembers what it last reported in `results/watch-<who>.json`: `all` for the orchestrator, `<slug>-orchestrator` for the first mate.
A watch started later still reports what happened while none ran, and `watch --now` marks the current state as seen.
A billing halt is an event too: `event halt=payment`.

The orchestrator never starts `watch` itself.
Its tab carries `FAST_CODING_ROLE`, `FAST_CODING_PROJECT`, and `FAST_CODING_REPO`, and the plugin's Stop hook (`fast-coding rewake`) parks a watch whenever one of its turns ends.
The watch's event wakes the idle session (Claude Code's `asyncRewake`), and the next turn end parks the next watch.
A lock keeps one watch per watcher: a second hook exits at once, and a second `watch` waits its turn.
The hook does nothing in any other session, and its watch ends with the session that parked it.
Restarting the orchestrator in its tab loses nothing: its first turn end reports whatever happened while it was down.
A `run` or `verify` it started keeps going meanwhile: those work in their own session, so a closed tab or a crashed session never ends them.
The first mate, and an orchestrator outside herdr, still run `watch` in the background themselves.
