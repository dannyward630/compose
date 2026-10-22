# Harnesses

A harness is the agent CLI a session runs in.
Compose runs its agents in Claude Code, in pi, in OpenCode, and in Codex.
This page says how a model id picks the harness, which harnesses exist, and which role runs in which.

- [What a harness is](#what-a-harness-is)
- [The prefix rule](#the-prefix-rule)
- [The harness table](#the-harness-table)
- [Which roles run where](#which-roles-run-where)
- [Models per harness](#models-per-harness)
- [Safety](#safety)
- [How to add a row](#how-to-add-a-row)
- [What is not covered yet](#what-is-not-covered-yet)

## What a harness is

Every agent in compose is a session in some agent CLI, and that CLI is its harness.
The model id you give a role picks the harness, so there is no separate setting for it.
The engineering manager runs in whichever CLI you started it in, and everything it starts runs in the harness its own model id names.

## The prefix rule

The start of a model id names the harness.

| Id | Harness | Runs |
|---|---|---|
| `claude:<model-id>` | Claude Code | that model |
| `claude` | Claude Code | its default model |
| `pi:<provider/model>` | pi | that provider's model |
| `codex:<model>` | Codex | that model |
| `codex` | Codex | its default model |
| anything else | OpenCode | that model id, for implementers only |

- `claude:`, `pi:` and each row key of the [harness table](#the-harness-table) (`codex:<model>`, and bare `codex`) name a harness.
- `codex`, `gemini` and `grok` are reserved: none of them can be a provider name under `providers` in the config, and a config that names one stops with a line saying so.
- Any other id is an OpenCode model id.
  OpenCode runs implementers, fallbacks and fix rounds only, never a teammate or a team lead.
- `gemini:` and `grok:` are not harness ids yet, see [What is not covered yet](#what-is-not-covered-yet).

## The harness table

`HARNESSES` in `bin/fc_harness.py` is the one table of harnesses beyond Claude Code and pi.
Every other module reads it through the accessors in that file, so nothing else names a harness.
A row is non-empty only when the harness is supported, and the row keys are the ids that start with it.

| Row key | What it holds |
|---|---|
| `codex` | Codex: the `codex` executable, its home (`CODEX_HOME`, else `~/.codex`), the `$` that starts its skill (`$compose`), the command that probes a model, the command that runs one headless turn, the `codex login status` check, and the hooks `compose setup` installs for it |
| `gemini` | reserved, with no row yet |
| `grok` | reserved, with no row yet |

The reserved names are exactly the keys of this table, so a new key reserves its name the moment it is added.

## Which roles run where

| Role | Runs in | Where it is decided |
|---|---|---|
| Engineering manager | the CLI you started it in: `claude` then `/compose`, or `codex` then `$compose` | `compose setup` prints the next line |
| Team lead | Claude Code, pi or Codex | `crew start`, through `models.crew` |
| Teammates (every other `crew start` session) | Claude Code, pi or Codex | `crew start`, through `models.crew` |
| Implementer, fallback, fix | Claude Code, pi, OpenCode or Codex | `models.implementer`, `models.fallback`, `models.fix` |
| `test_reader` | Claude Code or Codex | `models.test_reader` |

- The engineering manager is not started by compose.
  When Claude Code is not installed and another harness is set up, the last line of `compose setup` inside herdr is `next: run codex in a pane and type $compose`.
  Otherwise it is `next: run claude in a pane and type /compose`, and outside herdr it is `next: run compose to open herdr` either way.
- Teammates and the team lead run in Claude Code, pi or Codex.
  `crew start` stops on any other id, naming the three harnesses and ending with `OpenCode ids are for implementers only`.
- A Codex teammate needs a signed-in Codex.
  `crew start` checks `codex login status` first, and never signs in for you.
- An implementer, a fallback and a fix round on a `codex` id run through `codex exec`, headless and without a session, in the task's clone.
- `test_reader` runs the same way with a read-only sandbox, so the reader can point at a file and line but never edit or run anything.
  It takes a `claude:` or a `codex` id, and an id that names neither turns the reader off.

## Models per harness

Which model each role gets under a harness comes from that harness's `harnesses.<name>` block in `~/.compose/config.json`.
The block is merged over the top level, one level deep, so it only names what differs.
The session's harness is the `crew start --harness <name>` flag.
Without the flag it is `COMPOSE_HARNESS`.
Without that it is the harness whose own session variable is set, which for Codex is `CODEX_THREAD_ID`, so a session started by hand in Codex picks the `codex` block with no flag.
That check comes before `CLAUDECODE`, because a Codex started from a Claude Code shell still carries `CLAUDECODE=1`.
With none of them it is `claude` under Claude Code (`CLAUDECODE=1`), and `claude` has no block.
A harness other than `claude` with no block stops with a line saying so, and a block whose `models.crew` has no `default` stops too.

A block with no `designer` entry still gets the built-in designer default, `claude:claude-opus-5-5`, which needs Claude Code.

The block, its keys and what a bad entry does are in [config.md](config.md), so this page does not repeat them.

## Safety

A harness session runs tools on this machine, so this section is the page's safety half: what a session may do, and what compose never does.
For Codex, the only row in `HARNESSES` so far, the fences live in `bin/fc_harness.py`: `_codex_argv` for a crew session and `_codex_once` for a one-shot turn.

- A Codex teammate or the team lead runs in MH-9's fence: `-s workspace-write -a never`, the network on, and the cwd trusted.
- `--add-dir` gives the session the results folder and the checkout's git dirs, and the team lead also gets compose's config folder and the treehouse pool.
- A session may therefore write inside its cwd and every folder the fence adds, and it may use the network; with `-a never` it never waits on an approval prompt.
- The one-shot fence is a departure from MH-9's words the product owner confirmed (NEB-1533, 2026-10-22): the test reader's turn gets `-s read-only`, and every other one-shot turn gets `-s workspace-write` with the network on and `--add-dir` for the git dirs only.

- `compose setup` writes compose's hooks into the harness home's `hooks.json` and their trust records into its `config.toml`, merged into whatever is already there, never replaced.
- Each trust record is keyed by the resolved `hooks.json` path, so a symlinked `CODEX_HOME` still matches.
- compose never passes `--dangerously-bypass-hook-trust`.

- herdr gives every new pane the row's `home_env` (`CODEX_HOME`) when the caller has it set, and `PATH`; the pane rules are in [herdr.md](herdr.md).
- Before a Codex `crew start`, it runs the row's read-only sign-in check, `codex login status`, with the pane's home.
- compose never signs in, and it never presses a key on a sign-in screen: a failed check exits with `login_message`'s text, which names the `codex login` to run yourself.

- compose still starts on Python 3.9, so no module imports `tomllib` at module level.
- `trust_state` in `bin/fc_checks.py` reads the trust file's TOML by trying `import tomllib` inside the function, falling back to a line parser when the Python has no `tomllib` (3.9 does not).

## How to add a row

1. Add a non-empty row to `HARNESSES` in `bin/fc_harness.py`, under its reserved key when it has one.
   A row names the executable, the home variable and its default, the session variable, the sigil that starts the skill, an example model id, the probe, the headless command, the parser of its events, the sign-in check and the hooks.
2. Nothing else lists harnesses.
   `RESERVED` and `rows()` read the table, and `harness_of`, `crew_argv` and `once_command` choose the row from the model id.
3. Document the row key on this page, in the prefix rule and the table.
   A test reads `RESERVED` and `rows()`, so a row that is not here fails until it is.

## What is not covered yet

- Gemini (NEB-1490) and Grok (NEB-1524) are not supported yet.
  `gemini` and `grok` are reserved names with no row, so neither `gemini:` nor `grok:` runs anything.
- Outside herdr, bare `compose` prints `opening herdr session compose: run claude in a pane and type /compose`.
  It names only `claude` and `/compose`, also when Codex is the harness you set up.
