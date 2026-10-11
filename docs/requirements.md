# Requirements

Setup is one install pass per machine, then four steps to wire up your keys.
When you finish, fast-coding can run implementers on OpenRouter.

## Required

Install each of these once per machine.

| Tool | Needed for | Install |
|---|---|---|
| Python 3.9+ | `bin/fast-coding` itself (standard library only) | ships with macOS |
| git 2.30+ | task clones, branches, diffs | Xcode Command Line Tools or Homebrew |
| Node 22.19+ | pi, Lavish, the Frame0 MCP server, `node --test` repos | `brew install node` |
| pi | the default implementer harness | `npm install -g --ignore-scripts @earendil-works/pi-coding-agent` |
| Claude Code | the orchestrator, every crew session, model probes, `frame0` registration | [claude.com/claude-code](https://claude.com/claude-code) |
| OpenRouter account and key | implementers, fixers, Mercury review | see [Keys](#keys) |
| Linear account | the plan, stories, tasks, and decisions | Linear MCP connected in Claude Code; optional API key per [workspace](workspaces.md) |
| gh CLI and gh-stack | stacks and draft PRs | `brew install gh && gh extension install github/gh-stack`, then `git config rerere.enabled true` |
| macOS userland | `lsof`, `ps`, `pgrep`, `kill`, `open`: cleanup and launching Frame0 | ships with macOS |

If you skip gh-stack, you can still use `run --no-stack`.

## For verify

Verify needs these tools on top of the required ones.

| Tool | Needed for | Install |
|---|---|---|
| uv | runs `jev/` (Python 3.12+, fetched on first use) and Python test commands | `brew install uv`; `uv sync --project jev` once |
| TypeSafe account | Jev acceptance checks, every jev e2e step, and the decision screen (`reflect`) | key in `~/.fast-coding/.env` |
| Chrome and browser-harness | browser e2e cases | browser-harness comes with `jev/`; check with `cd jev && uv run browser-harness --doctor` |
| `bp` (browser-probe) | browser exploration and extension e2e | `npm link` in a browser-probe checkout |

## Optional

Each optional tool adds one feature.

| Tool | Unlocks | Install |
|---|---|---|
| herdr | the visible fleet: crews, panes, one space per project ([herdr.md](herdr.md)) | herdr's installer; without it everything runs headless in one session |
| treehouse | worktrees from a pool inside the repo | `curl -fsSL https://kunchenguid.github.io/treehouse/install.sh \| sh`; plain git worktrees without it |
| graft | `file:line` context packs for implementers | `brew install graft` |
| Frame0 1.7.0+ | wireframes for prototype questions (macOS) | [frame0.app](https://frame0.app); the MCP server comes through `npx` |
| OpenCode | an alternative implementer per task, a `bench` column | `curl -fsSL https://opencode.ai/install \| bash` |

fast-coding also uses gofmt and the target repo's own prettier when they are present.
They format a task's files.
When the pi herdr extension `~/.pi/agent/extensions/herdr-agent-state.ts` is present, pi implementers use it to report their state to herdr.

`npx` fetches two tools on every use, with no pinned version.
They are `lavish-axi` (the wayfinder page) and `frame0-mcp-server`.

## Keys

The implementers run on OpenRouter.

1. Put the key in pi's auth store, `~/.pi/agent/auth.json`, under `openrouter` and `openrouter-fast`.
2. Declare the provider `openrouter-fast` in `~/.pi/agent/models.json`.
   Use base `https://openrouter.ai/api/v1`, api `openai-completions`, and model `z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast` priced 0.15/0.50 per million tokens.
3. Create the OpenRouter preset `glm-5-3-flash-fast` under Settings > Presets.
   Use model `z-ai/glm-5.3-flash`, provider order Together then CoreWeave, and fallbacks off.
4. Write `~/.fast-coding/.env` (mode 600) with `TEXT_MODEL`, `TEXT_MODEL_BASE_URL`, `TEXT_MODEL_API_KEY`, `TYPESAFE_API_KEY`, and `TYPESAFE_MODEL`.
   `TEXT_MODEL_API_KEY` takes the same OpenRouter key.

The active [workspace](workspaces.md) key overrides all of these.
The process environment wins over `~/.fast-coding/.env`.
Secrets never live in this repo or on Linear issues.

For OpenCode, keep the key in `~/.local/share/opencode/auth.json` and pin `options.provider.order: ["cerebras", "groq"]` in `~/.config/opencode/opencode.jsonc`.
You need the `gpt-oss-120b-cerebras` preset (model `openai/gpt-oss-120b`, provider Cerebras) only for `bench` or an opt-in fallback.

## Files outside the repo

| Path | What |
|---|---|
| `~/.fast-coding/config.json` | workspaces, their keys, model choices (`FAST_CODING_CONFIG` moves it) |
| `~/.fast-coding/.env` | verify's model keys |
| `~/.fast-coding/model-probe.json` | the day's model availability probes |
| `~/.fast-coding/tool-bugs.jsonl` | every project's tool-bug reports |
| `~/.claude.json` | read for folder trust; each crew directory's local `frame0` MCP server is written here |
| `~/.pi/agent/` | pi's `models.json`, `auth.json`, and the herdr extension |

## Environment variables

| Variable | Effect |
|---|---|
| `FAST_CODING_CONFIG` | path of the config file |
| `FAST_CODING_NO_TREEHOUSE=1` | use plain git worktrees even with treehouse installed |
| `FAST_CODING_NO_GRAFT=1` | skip graft |
| `FAST_CODING_FAKE_402=<provider>` | simulate a billing halt (tests) |
| `HERDR_ENV=1` with `HERDR_SOCKET_PATH` | marks a session inside herdr |
