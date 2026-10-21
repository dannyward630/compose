# Requirements

`compose setup` installs and configures everything on this page except Claude Code ([new-machine.md](new-machine.md)).
This page says what each piece is for, and which pieces setup treats as required, default-on, or opt-in.

## Required

`compose doctor` exits 1 while one of these is missing.

| Tool | Needed for | Install |
|---|---|---|
| Python 3.9+ | the CLI core, `bin/compose` (standard library only) | ships with macOS |
| git 2.30+ | task clones, branches, diffs | `xcode-select --install`; setup only reports it |
| Node 22.19+ | pi, Lavish, the Frame0 MCP server, `node --test` repos | setup runs `brew install node` |
| gh CLI and gh-stack | stacks and draft PRs | setup runs `brew install gh` and `gh extension install github/gh-stack`; you run `gh auth login` |
| herdr | the visible fleet, and the session `compose` opens ([herdr.md](herdr.md)) | setup runs herdr's installer, installs the herdr skill file, and sets the notification lines |
| pi | the default implementer harness | setup runs `npm install -g --ignore-scripts @earendil-works/pi-coding-agent` and declares its `openrouter-fast` provider |
| Claude Code | the team lead, every teammate session, model probes, `frame0` registration | [claude.com/claude-code](https://claude.com/claude-code); setup does not install it |
| i-have-adhd skill | the skill file `doctor` requires | setup adds its marketplace (needs Claude Code) |
| OpenRouter key | implementers, fixers, Mercury review | see [Keys](#keys) |
| TypeSafe key | Jev acceptance checks, every jev e2e step, and the decision screen (`reflect`) | see [Keys](#keys) |
| Linear | the plan, stories, tasks, and decisions | a Linear API key per [workspace](workspaces.md); required |
| macOS userland | `lsof`, `ps`, `pgrep`, `kill`, `open`: cleanup and launching Frame0 | ships with macOS |

`~/.local/bin` must be on your PATH, because the links setup makes live there.
Setup prints the line to add and never edits your shell profile.

## On by default

Setup installs these unless you skip them.
`doctor` lists a missing one as `MISSING ... - optional`.

| Tool | Needed for | Install |
|---|---|---|
| uv | runs `jev/` (Python 3.12+, fetched on first use) and the setup screen | setup runs uv's installer, then `uv sync --locked --project jev` |
| Chrome and browser-harness | browser e2e cases | browser-harness comes with `jev/`; check with `cd jev && uv run browser-harness --doctor` |
| `bp` and Chromium | browser exploration and extension e2e ([bp/README.md](../bp/README.md)) | setup links `bp/bin/bp.mjs` into `~/.local/bin` and runs `npx playwright install chromium` |
| treehouse | worktrees from a pool inside the repo; plain git worktrees without it | `curl -fsSL https://kunchenguid.github.io/treehouse/install.sh \| sh` |
| trail | `file:line` context packs for implementers | `npm i -g @trailhq/trail-code` |
| superpowers plugin | the writing-plans skill (needs Claude Code) | `claude plugin install superpowers@claude-plugins-official` |
| herdr integrations | herdr shows pi and Claude Code agents' state (the Claude one needs Claude Code) | `herdr integration install pi`, `herdr integration install claude` |
| herdr config | herdr's own toasts and sounds stay off | setup writes it ([new-machine.md](new-machine.md#herdr-settings)) |
| `TEXT_MODEL` lines | the Mercury review and jev's text helper | setup adds them to `~/.compose/.env` when absent |
| git rerere | stacks that rebase cleanly | `git config --global rerere.enabled true`, set only when unset |

If you skip gh-stack, you can still use `run --no-stack`.

## Opt-in

Setup does not install these for you by default.

| Tool | Unlocks | Install |
|---|---|---|
| Framelink (`framelink-figma` MCP server) | every Figma read: the designer, its builders and reviewer, `figma check`, `figma tree` | pick the designer rows in `compose setup`; they need Claude Code. By hand: a Figma personal access token in `~/.config/figma-context-mcp/.env` as one line `FIGMA_API_KEY=<token>` (mode 600), then `claude mcp add framelink-figma --scope user -- npx -y figma-developer-mcp --stdio --env ~/.config/figma-context-mcp/.env --no-telemetry` |
| Frame0 1.7.0+ | wireframes for prototype questions (macOS) | [frame0.app](https://frame0.app); the MCP server comes through `npx` |
| OpenCode | an alternative implementer per task, a `bench` column | `curl -fsSL https://opencode.ai/install \| bash` |

Without Framelink, `doctor` prints one line, `designer extras not set up`, and the designer's start stops.
Setup has no step for Frame0 or OpenCode.

`compose` also uses gofmt and the target repo's own prettier when they are present.
They format a task's files.
When the pi herdr extension `~/.pi/agent/extensions/herdr-agent-state.ts` is present, pi implementers use it to report their state to herdr.

`npx` fetches three tools on every use, with no pinned version.
They are `lavish-axi` (the wayfinder page), `frame0-mcp-server`, and `figma-developer-mcp` (Framelink).

## Keys

Every key lives in `~/.compose/auth.json`, mode 600 in a directory of mode 700.
Keys never go in git, on Linear issues, or on a command line.

1. Enter the keys in `compose setup`, or set one later: `pbpaste | compose workspace key <name>` for a workspace's OpenRouter key, with `--linear` for its Linear key, and `pbpaste | compose workspace key default --typesafe` for the TypeSafe key, which every workspace shares ([workspaces.md](workspaces.md)).
2. Create the OpenRouter preset `glm-5-3-flash-fast` under Settings > Presets.
   Use model `z-ai/glm-5.3-flash`, provider order Together then CoreWeave, and fallbacks off.
   An OpenRouter account holds its presets, so setup can only print these steps.
3. pi gets its key from the environment: setup declares the `openrouter-fast` provider in `~/.pi/agent/models.json` with `"apiKey": "$OPENROUTER_API_KEY"`, base `https://openrouter.ai/api/v1`, api `openai-completions`, and model `z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast` priced 0.15/0.50 per million tokens.
   An `openrouter-fast` already there keeps its fields; setup adds the `apiKey` and that model when it lacks them, and `doctor` fails the provider until it has both.
   `compose` exports the active workspace's key as `OPENROUTER_API_KEY` and `TEXT_MODEL_API_KEY`, and the TypeSafe key as `TYPESAFE_API_KEY`.
   pi reads its own `~/.pi/agent/auth.json` first, so an `openrouter` or `openrouter-fast` entry there overrides the workspace key; remove it (`doctor` and setup flag it).
4. `~/.compose/.env` keeps only non-secret lines: `TEXT_MODEL`, `TEXT_MODEL_BASE_URL`, and the optional `TEXT_MODEL_REASONING` and `TYPESAFE_MODEL`.

The first command after an upgrade moves any key still in `~/.compose/config.json` or `~/.compose/.env` into `auth.json` and prints one line per key.
A key that differs from the one `auth.json` already holds stays where it is, and `doctor` warns until you remove the one you do not want.
The active [workspace](workspaces.md) key overrides the shell's.
The process environment wins over `~/.compose/.env`.

For OpenCode, `compose` writes its key file from `auth.json`.
Pin `options.provider.order: ["cerebras", "groq"]` in `~/.config/opencode/opencode.jsonc`.
You need the `gpt-oss-120b-cerebras` preset (model `openai/gpt-oss-120b`, provider Cerebras) only for `bench` or an opt-in fallback.

## Files outside the repo

| Path | What |
|---|---|
| `~/.compose/auth.json` | every key (mode 600 in a 700 directory) |
| `~/.compose/config.json` | workspaces, model choices, `parallel`, extra env; no keys (`COMPOSE_CONFIG` moves it and the files below beside it) |
| `~/.compose/src/` | the checkout the installer makes, unless `COMPOSE_INSTALL_DIR` or an existing skill link names another |
| `~/.compose/skill-seen/` | the skill files each session last saw |
| `~/.compose/.env` | verify's `TEXT_MODEL*` and `TYPESAFE_MODEL` lines, no keys |
| `~/.compose/model-probe.json` | the day's model availability probes |
| `~/.compose/tool-bugs.jsonl` | every project's tool-bug reports, with the issue URL once filed |
| `~/.claude.json` | read for folder trust and the user-scope `framelink-figma` MCP server; the local `frame0` MCP server for each teammate's directory is written here |
| `~/.config/figma-context-mcp/.env` | Framelink's Figma token (mode 600); it never goes on a command line |
| `~/.pi/agent/` | pi's `models.json` (setup declares `openrouter-fast`), its own `auth.json`, and the herdr extension |
| `~/.config/herdr/config.toml` | herdr's config: copied from `bin/herdr.toml` when absent, else only the two notification lines are set |

## Read only when present

These need no install.
`compose` uses them when they exist, and never fails when they do not.

| Tool | Used for |
|---|---|
| `caffeinate` (macOS) | keeps the Mac awake while a run, resume, verify, watch, or live teammate works (`caffeinate -dims -w <pid>`) |
| `pmset` (macOS) | `doctor` and the start of a run warn when the Mac is on battery, because closing the lid sleeps it |
| docker | `doctor` and the start of a run warn about a container that keeps restarting, only when docker is installed and running |

## Environment variables

| Variable | Effect |
|---|---|
| `COMPOSE_NO_PREFLIGHT=1` | `doctor` and the start of `run`, `resume`, and `verify` skip the key calls, the gh login check, and the machine warnings (offline work); the uncommitted-changes check stays |
| `COMPOSE_NO_AWAKE=1` | `run`, `verify`, `watch`, and `crew start` start no `caffeinate`, so the Mac may sleep mid-run (the test suite sets it) |
| `COMPOSE_CONFIG` | path of the config file; the files beside it in `~/.compose/` move with it. Project code that `run`, `verify`, and `compose timed` start gets one in a fresh scratch directory, and a change to `~/.compose` while it runs prints a `WARNING`, unless a compose outside it made that change (another session's `compose workspace`, say; compose journals each write it makes there in `~/.compose/home-writes.jsonl`) or it is in the CLI checkout |
| `COMPOSE_NO_TREEHOUSE=1` | use plain git worktrees even with treehouse installed |
| `COMPOSE_NO_TRAIL=1` | skip trail |
| `COMPOSE_TEST_SLOTS=<n>` | how many full-suite `compose timed` commands run at once on this machine (default 2); the next waits for a slot and says so. `COMPOSE_QUICK_SLOTS=<n>` is the same for every other command (`--help`, `uv sync`, or a test run with a `-k`/`-run`/`--grep` filter or one test file or module), in lanes apart from the suites (default 2) |
| `COMPOSE_NO_HERDR=1` | bare `compose` does not open the herdr session; it prints the usage. Every subcommand runs headless, inside herdr too: no space, tab, pane, or agent |
| `COMPOSE_INSTALL_DIR` | where `install.sh` puts the checkout (default `~/.compose/src`) |
| `COMPOSE_FAKE_402=<provider>` | simulate a billing halt (tests) |
| `HERDR_ENV=1` with `HERDR_SOCKET_PATH` | marks a session inside herdr |

Bare `compose` outside herdr, on a terminal, attaches the herdr session `compose`, and creates it when it is missing.
It does so only when stdin and stdout are terminals and none of `HERDR_ENV`, `CI`, and `COMPOSE_NO_HERDR` is set.
Otherwise it prints the usage and exits 2.
When herdr is not installed it prints herdr's install line, "or run compose setup", and exits 1.
Every subcommand runs headless as before, so scripts, hooks, and teammates are unaffected.
