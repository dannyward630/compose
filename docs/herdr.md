# Running inside herdr

Inside [herdr](https://herdr.dev) you can see every agent in the fleet and steer any of them.
Outside it, the same commands run headless in one session.

## Roles

You are the product owner.
The roles are adapted from [firstmate](https://github.com/kunchenguid/firstmate).

| Role | Who | Where |
|---|---|---|
| engineering manager | the Claude session you started; creates the project, then only relays | the pane you started it in |
| team lead | runs the project from wayfinder to a verified stack | tab `orchestrator`, agent `<slug>-orchestrator` |
| designer | continues design work in Figma from where it stopped | tab `designer`, agent `<slug>-designer` |
| design-NNN | one builder per design task, Claude only | tab `design NNN` |
| design-review | one screenshot per story, findings confirmed by quoting nodes | tab `design-review` |
| teammates | explore, wayfinder, groundwork, test writers, helpers, implementers | one tab each in the project's space |
| planner | continues specing a ticket at step 1, 2, or 8 and cuts the task issues | tab `planner`, agent `<slug>-planner` |

The engineering manager and the team lead write no code.
For the team lead the plugin enforces this.
The team lead's and the planner's tabs are both marked (`COMPOSE_ROLE=orchestrator` or `planner`) and denied edits by the plugin's PreToolUse hook (`compose guard`), except the CLI's JSON under `.compose/`.
The team lead starts the planner after wayfinder, or you start it with `/compose:planner <ticket>` from the engineering manager.

## Talking to the fleet

You talk to the engineering manager, and you can also type into any teammate's tab directly.
Teammates report up with `compose report` and pick a state from `working`, `needs-user`, `blocked`, `done`, `tool-bug`, and `contradiction`.
`compose toolsmith` only prints the toolsmith's brief.
The toolsmith it briefs files the tool-bug as an issue on prodoxx/compose with `compose tool-bug file`, which needs gh logged in to post.

A `contradiction` report always wakes the team lead as a teammate event.
It also screens the feature's decisions with Jev, which adds a `reflect=` event when it flags a decision line.

A `needs-user` or `blocked` report badges the pane `needs you`.
The desktop notification pops only when such a report wakes the engineering manager's `watch`, so you are alerted once, for what the engineering manager brings you, and not by every teammate or the team lead.
The CLI sends it itself (macOS `osascript`, elsewhere `notify-send`), not through herdr: herdr's own toast and sound fire for every agent that finishes or needs input, so set `[ui.toast] delivery = "off"` and `[ui.sound] enabled = false` in `~/.config/herdr/config.toml`; `compose doctor` warns while either is on.
Nothing steals focus.
When you want to jump to a tab, `compose crew focus --role <role>` takes you there.

## Teammate commands

These commands start, list, and stop teammates.

```bash
compose crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt
compose explore --project <slug> | compose crew start --project <slug> --role explore --title explore --brief -
compose wayfinder --project <slug> --extra - < notes.md | compose crew start --project <slug> --role wayfinder --title wayfinder --brief -
compose crew list --project <slug>
compose crew stop --project <slug> --role wayfinder   # refused until it reported done; --force overrides
compose testcrews --project <slug>                    # one test-writing teammate per task
compose figma check --project <slug> --figma <url or key>
compose designer --project <slug> | compose crew start --project <slug> --role designer --title designer --brief -
compose designcrews --project <slug>   # one design-NNN builder per open design task
compose teardown --project <slug>                     # close finished tabs; the team lead's done runs it
```

The config sets the model for each teammate role, as [workspaces.md](workspaces.md#crew-models) explains.

## Layout

Each project gets its own herdr space, laid out like this.

| herdr | `compose` | Label |
|---|---|---|
| space | one project | `<slug>` |
| tab | live `compose status --watch` | `status` |
| tab | every implementer, one pane per task | `implementers` |
| pane | one task's interactive pi session | `NNN <title>`, agent `<slug>-NNN` |
| tab | the latest verify run, one pane per stage | `verify` |
| tab | the team lead | `orchestrator` |
| tab | one teammate session | its title, agent `<slug>-<role>` |

Each task pane shows its state, such as `attempt 2/3` or `passed`, along with its model and cost.
The team lead steers a working or blocked implementer with `herdr agent prompt <slug>-NNN "..."`.
That prompt lands in the same pi session the CLI drives.
`clean` closes the project's space along with its worktree.

## Supervision

`compose watch --project <slug>` sleeps until a task finishes, an agent blocks, a teammate reports, a run ends, or verify finishes.
It prints one `event ...` line and exits, so a waiting team lead spends no tokens.
`--from orchestrator` makes the engineering manager wake on the team lead's reports, on a tool-bug (to start a toolsmith) or a stall, and on any teammate it started itself.
`crew start` records who each teammate reports to (`reports_to` in `results/crew/<agent>.json`), so a planner or designer the engineering manager started needs no second watch.
A run left silent with work pending raises a stall event after 240 s.
You can change that limit with `stall_seconds` in `verify.json` or with `watch --stall`.

Each watcher remembers what it last reported in `results/watch-<who>.json`.
The `<who>` is `all` for the team lead and `<slug>-orchestrator` for the engineering manager.
A watch started later still reports what happened while none ran, and `watch --now` marks the current state as seen.
A billing halt is an event too, shown as `event halt=payment`.

The team lead never starts `watch` itself.
Its tab carries `COMPOSE_ROLE`, `COMPOSE_PROJECT`, and `COMPOSE_REPO`, and the plugin's Stop hook (`compose rewake`) parks a watch whenever one of its turns ends.
The watch's event wakes the idle session (Claude Code's `asyncRewake`), and the next turn end parks the next watch.
A lock keeps one watch per watcher.
A second hook exits at once, and a second `watch` waits its turn.
The hook does nothing in any other session, and its watch ends with the session that parked it.

Restarting the team lead in its tab loses nothing, because its first turn end reports whatever happened while it was down.
A `run` or `verify` it started keeps going meanwhile.
Those work in their own session, so a closed tab or a crashed session never ends them.
The engineering manager, and a team lead outside herdr, still run `watch` in the background themselves.
