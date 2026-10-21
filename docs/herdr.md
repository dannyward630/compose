# Running inside herdr

Inside [herdr](https://herdr.dev) you can see every agent in the fleet and steer any of them.
`compose` with no command, run on a terminal outside herdr, opens the herdr session `compose` for you: `herdr session attach compose`, which creates the session when it is missing.
It prints one hint line first, then you run `claude` in a pane and type `/compose`.
`COMPOSE_NO_HERDR=1` turns that off, and inside herdr it keeps every command headless too: no space, tab, pane, or agent.
Every subcommand runs headless as before, and a team lead started outside herdr works in one session.

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

herdr agent names stop at 32 characters, so a longer `<slug>-<role>` keeps its role and cuts the slug.
Project `clean-recut-branches` has team lead `clean-recut-branche-orchestrator`, and `init` says so when it creates such a project.
Use the name `compose crew list` shows in every `herdr agent` command; `watch --from` takes the role.

The engineering manager is the session you started, so compose sets neither its model nor its compaction.
It relays and supervises while planning goes to the wayfinder on the strongest model, so Sonnet serves it well.
Cap its context with `"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"` in the `env` of `~/.claude/settings.json`, as compose caps every teammate at 150k.
That variable outranks `modelSettings.<model>.autoCompactWindow` and the `--autocompact` flag, and a session reads it only when it starts.

The engineering manager and the team lead write no code.
For the team lead the plugin enforces this.
The team lead's and the planner's tabs are both marked (`COMPOSE_ROLE=orchestrator` or `planner`) and denied edits by the plugin's PreToolUse hook (`compose guard`), except the CLI's JSON under `.compose/`.
The team lead starts the planner after wayfinder, or you start it with `/compose:planner <ticket>` from the engineering manager.

## Talking to the fleet

You talk to the engineering manager, and you can also type into any teammate's tab directly.
Teammates report up with `compose report` and pick a state from `working`, `needs-user`, `blocked`, `done`, `tool-bug`, and `contradiction`.
`compose toolsmith` only prints the toolsmith's brief.
The toolsmith it briefs files the tool-bug as an issue on prodoxx/compose with `compose tool-bug file`, which needs gh logged in to post, and on the maintainer's machine opens its fix from its own worktree as a PR with `compose tool-bug pr`; it never commits on main or in the installed copy.

A `contradiction` report always wakes the team lead as a teammate event.
It also screens the feature's decisions with Jev, which adds a `reflect=` event when it flags a decision line.

A `needs-user` or `blocked` report badges the pane `needs you`.
A `needs-user` that names a Lavish page is refused unless it carries the page's one working link, and cards already asked and not answered are not asked again.
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

A project opens as a herdr worktree space of its own, labelled `<slug>`, grouped under the space open on its repo, laid out like this.
`init` uses the repo's space it was started from, or any open space of the repo, and opens no other space.

| herdr | `compose` | Label |
|---|---|---|
| space | the project worktree, grouped under the repo's space | `<slug>` |
| tab | a shell in the project worktree | `shell` |
| tab | live `compose status --watch` | `status` |
| tab | every implementer, one pane per task | `implementers` |
| pane | one task's interactive pi session | `NNN <title>`, agent `<slug>-NNN` |
| tab | the latest verify run, one pane per stage | `verify` |
| tab | the team lead | `orchestrator` |
| tab | one teammate session | its title, agent `<slug>-<role>` |

When no space of the project's repo is open, such as when compose runs from another repo's space, the project opens in the space `init` was started from instead, with no new space.
There every tab carries the project's name first (`<slug> status`), so several projects share one space without touching each other's tabs.
That space is recorded in the project's `results/herdr.json`, so every later command finds it, and the project stays there while it is open.

Each task pane shows its state, such as `attempt 2/3` or `passed`, along with its model and cost.
The team lead steers a working or blocked implementer with `herdr agent prompt <slug>-NNN "..."`.
That prompt lands in the same pi session the CLI drives.
When herdr sees no work within 5 s of a CLI prompt (`agent_prompt_stalled`), the CLI keeps the pane and waits for the turn, or reads it from the pi session file when herdr never sees it working.
A prompt pi never records within 30 s is sent once more to the same session, and only a turn that still never starts ends as a timeout and costs an attempt.
`clean` closes the project's space along with its worktree, or in a shared space only the project's tabs.
While the team lead has not reported done, `clean` keeps both, and the team lead's `done` closes them once its turn ends.

## Supervision

`compose watch --project <slug>` sleeps until a task finishes, an agent blocks, a teammate reports, a run ends, or verify finishes.
It prints one `event ...` line and exits, so a waiting team lead spends no tokens.
`--from orchestrator` makes the engineering manager wake on the team lead's reports, on a tool-bug (to start a toolsmith) or a stall, and on any teammate it started itself.
`crew start` records who each teammate reports to (`reports_to` in `results/crew/<agent>.json`), so a planner or designer the engineering manager started needs no second watch.
It also records the session that started it (`started_by`, its herdr pane).
With two engineering manager sessions on one project, each session's watch wakes on no line of a teammate another live session started, unless `--from` names it.
A teammate whose starting session has ended is adopted by any engineering manager's watch.
One engineering manager session drives a project (`results/manager.json`, the herdr pane that first ran `crew start`, `crew stop`, or a continuous `watch`).
The same from another session while that pane still holds a live agent refuses, naming the pane; `watch --now` and `status --digest` stay read-only and `--takeover` moves the claim and the owner's teammates to the new session.
An owner whose pane is gone is replaced silently, and outside herdr nothing is claimed.
The watch spends few wake-ups: a task starting is not an event, a teammate's plain `working` report travels with the next wake (or alone after 5 minutes), a burst of non-urgent events is one wake after a 10 s settle, and the watch never times out.
For the product owner it adds `event tell='<line>'` on a state change only: verify failed and why, fix loop started, run ended or crashed, verify passed, done.
A teammate idle for a minute whose last report is `working` and whose pane ends on an API or network error raises `event stall=network` once, with the nudge to send when the network is back.
A run left silent with work pending raises a stall event after 240 s.
You can change that limit with `stall_seconds` in `verify.json` or with `watch --stall`.

Each watcher remembers what it last reported in `results/watch-<who>.json`.
The `<who>` is the watcher's `COMPOSE_ROLE` (`orchestrator` for the team lead), and `manager-<pane>` for an engineering manager session in herdr pane `<pane>` (`manager` outside herdr).
`watch --now` and `status` also say whether away or yolo is on and which session set it, since one session's `compose away` or `compose yolo` changes how every session on the project answers.
A watch started later still reports what happened while none ran, and `watch --now` marks the current state as seen.
A billing halt is an event too, shown as `event halt=payment`.

The team lead never starts `watch` itself.
Its tab carries `COMPOSE_ROLE`, `COMPOSE_PROJECT`, and `COMPOSE_REPO`, and the plugin's Stop hook (`compose rewake`) parks a watch whenever one of its turns ends.
The watch's event wakes the idle session (Claude Code's `asyncRewake`), and the next turn end parks the next watch.
A lock keeps one watch per watcher.
A second hook exits at once, and a second `watch` waits its turn.
The hook does nothing in any other session, and its watch ends with the session that parked it.
Every Claude teammate compacts at 150k tokens, since every turn re-sends the whole session and a long one pays for its size on each of them.
The window is `CLAUDE_CODE_AUTO_COMPACT_WINDOW` in the session's `--settings` env, because that variable outranks the `--autocompact` flag and would let a value in your own settings win.
After a context compaction, the plugin's SessionStart hook (`compose reenter`) points any teammate back at its own brief, `results/crew/<agent>.brief.md`.
Every teammate's tab carries its name in `COMPOSE_TEAMMATE` for that, since `COMPOSE_ROLE` is `crew` for all but the team lead and the planner.

Restarting the team lead in its tab loses nothing, because its first turn end reports whatever happened while it was down.
A `run` or `verify` it started keeps going meanwhile.
Those work in their own session, so a closed tab or a crashed session never ends them.
The engineering manager, and a team lead outside herdr, still run `watch` in the background themselves.
