# Running inside herdr

Inside [herdr](https://herdr.dev) you can see every agent in the fleet and steer any of them.
Outside it, the same commands run headless in one session.

## Roles

You are the captain.
The roles are adapted from [firstmate](https://github.com/kunchenguid/firstmate).

| Role | Who | Where |
|---|---|---|
| team lead | the Claude session you started; creates the project, then only relays | the pane you started it in |
| orchestrator | runs the project from wayfinder to a verified stack | tab `orchestrator`, agent `<slug>-orchestrator` |
| crew | explore, wayfinder, groundwork, test writers, helpers, implementers | one tab each in the project's space |

The team lead and the orchestrator write no code.
For the orchestrator the plugin enforces this.
Its tab is marked `FAST_CODING_ROLE=orchestrator`, and the plugin's PreToolUse hook (`fast-coding guard`) denies its edits except the CLI's JSON under `.fast-coding/`.

## Talking to the fleet

You talk to the team lead, and you can also type into any crew tab directly.
Crews report up with `fast-coding report` and pick a state from `working`, `needs-user`, `blocked`, `done`, `tool-bug`, and `contradiction`.

A `contradiction` report always wakes the orchestrator as a crew event.
It also screens the feature's decisions with Jev, which adds a `reflect=` event when it flags a decision line.

A `needs-user` or `blocked` report pops a herdr notification and badges the pane `needs you`.
Nothing steals focus.
When you want to jump to a tab, `fast-coding crew focus --role <role>` takes you there.

## Crew commands

These commands start, list, and stop crews.

```bash
fast-coding crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt
fast-coding explore --project <slug> | fast-coding crew start --project <slug> --role explore --title explore --brief -
fast-coding wayfinder --project <slug> --extra - < notes.md | fast-coding crew start --project <slug> --role wayfinder --title wayfinder --brief -
fast-coding crew list --project <slug>
fast-coding crew stop --project <slug> --role wayfinder   # refused until it reported done; --force overrides
fast-coding testcrews --project <slug>                    # one test-writing crew per task
fast-coding teardown --project <slug>                     # close finished tabs; the orchestrator's done runs it
```

The config sets the model for each crew role, as [workspaces.md](workspaces.md#crew-models) explains.

## Layout

Each project gets its own herdr space, laid out like this.

| herdr | fast-coding | Label |
|---|---|---|
| space | one project | `<slug>` |
| tab | live `fast-coding status --watch` | `status` |
| tab | every implementer, one pane per task | `implementers` |
| pane | one task's interactive pi session | `NNN <title>`, agent `<slug>-NNN` |
| tab | the latest verify run, one pane per stage | `verify` |
| tab | the orchestrator | `orchestrator` |
| tab | one crew session | its title, agent `<slug>-<role>` |

Each task pane shows its state, such as `attempt 2/3` or `passed`, along with its model and cost.
The orchestrator steers a working or blocked implementer with `herdr agent prompt <slug>-NNN "..."`.
That prompt lands in the same pi session the CLI drives.
`clean` closes the project's space along with its worktree.

## Supervision

`fast-coding watch --project <slug>` sleeps until a task finishes, an agent blocks, a crew reports, a run ends, or verify finishes.
It prints one `event ...` line and exits, so a waiting orchestrator spends no tokens.
`--from orchestrator` makes the team lead wake only on the orchestrator's reports.
A run left silent with work pending raises a stall event after 240 s.
You can change that limit with `stall_seconds` in `verify.json` or with `watch --stall`.

Each watcher remembers what it last reported in `results/watch-<who>.json`.
The `<who>` is `all` for the orchestrator and `<slug>-orchestrator` for the team lead.
A watch started later still reports what happened while none ran, and `watch --now` marks the current state as seen.
A billing halt is an event too, shown as `event halt=payment`.

The orchestrator never starts `watch` itself.
Its tab carries `FAST_CODING_ROLE`, `FAST_CODING_PROJECT`, and `FAST_CODING_REPO`, and the plugin's Stop hook (`fast-coding rewake`) parks a watch whenever one of its turns ends.
The watch's event wakes the idle session (Claude Code's `asyncRewake`), and the next turn end parks the next watch.
A lock keeps one watch per watcher.
A second hook exits at once, and a second `watch` waits its turn.
The hook does nothing in any other session, and its watch ends with the session that parked it.

Restarting the orchestrator in its tab loses nothing, because its first turn end reports whatever happened while it was down.
A `run` or `verify` it started keeps going meanwhile.
Those work in their own session, so a closed tab or a crashed session never ends them.
The team lead, and an orchestrator outside herdr, still run `watch` in the background themselves.
