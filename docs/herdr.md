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
The team lead's and the planner's tabs are both marked (`FAST_CODING_ROLE=orchestrator` or `planner`) and denied edits by the plugin's PreToolUse hook (`fast-coding guard`), except the CLI's JSON under `.fast-coding/`.
The team lead starts the planner after wayfinder, or you start it with `/fast-coding:planner <ticket>` from the engineering manager.

## Talking to the fleet

You talk to the engineering manager, and you can also type into any teammate's tab directly.
Teammates report up with `fast-coding report` and pick a state from `working`, `needs-user`, `blocked`, `done`, `tool-bug`, and `contradiction`.

A `contradiction` report always wakes the team lead as a teammate event.
It also screens the feature's decisions with Jev, which adds a `reflect=` event when it flags a decision line.

A `needs-user` or `blocked` report pops a herdr notification and badges the pane `needs you`.
Nothing steals focus.
When you want to jump to a tab, `fast-coding crew focus --role <role>` takes you there.

## Teammate commands

These commands start, list, and stop teammates.

```bash
fast-coding crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt
fast-coding explore --project <slug> | fast-coding crew start --project <slug> --role explore --title explore --brief -
fast-coding wayfinder --project <slug> --extra - < notes.md | fast-coding crew start --project <slug> --role wayfinder --title wayfinder --brief -
fast-coding crew list --project <slug>
fast-coding crew stop --project <slug> --role wayfinder   # refused until it reported done; --force overrides
fast-coding testcrews --project <slug>                    # one test-writing teammate per task
fast-coding figma check --project <slug> --figma <url or key>
fast-coding designer --project <slug> | fast-coding crew start --project <slug> --role designer --title designer --brief -
fast-coding designcrews --project <slug>   # one design-NNN builder per open design task
fast-coding teardown --project <slug>                     # close finished tabs; the team lead's done runs it
```

The config sets the model for each teammate role, as [workspaces.md](workspaces.md#crew-models) explains.

## Layout

Each project gets its own herdr space, laid out like this.

| herdr | fast-coding | Label |
|---|---|---|
| space | one project | `<slug>` |
| tab | live `fast-coding status --watch` | `status` |
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

`fast-coding watch --project <slug>` sleeps until a task finishes, an agent blocks, a teammate reports, a run ends, or verify finishes.
It prints one `event ...` line and exits, so a waiting team lead spends no tokens.
`--from orchestrator` makes the engineering manager wake only on the team lead's reports.
A run left silent with work pending raises a stall event after 240 s.
You can change that limit with `stall_seconds` in `verify.json` or with `watch --stall`.

Each watcher remembers what it last reported in `results/watch-<who>.json`.
The `<who>` is `all` for the team lead and `<slug>-orchestrator` for the engineering manager.
A watch started later still reports what happened while none ran, and `watch --now` marks the current state as seen.
A billing halt is an event too, shown as `event halt=payment`.

The team lead never starts `watch` itself.
Its tab carries `FAST_CODING_ROLE`, `FAST_CODING_PROJECT`, and `FAST_CODING_REPO`, and the plugin's Stop hook (`fast-coding rewake`) parks a watch whenever one of its turns ends.
The watch's event wakes the idle session (Claude Code's `asyncRewake`), and the next turn end parks the next watch.
A lock keeps one watch per watcher.
A second hook exits at once, and a second `watch` waits its turn.
The hook does nothing in any other session, and its watch ends with the session that parked it.

Restarting the team lead in its tab loses nothing, because its first turn end reports whatever happened while it was down.
A `run` or `verify` it started keeps going meanwhile.
Those work in their own session, so a closed tab or a crashed session never ends them.
The engineering manager, and a team lead outside herdr, still run `watch` in the background themselves.
