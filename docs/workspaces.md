# Workspaces

Setting up a workspace takes a few commands and one config file.
When you finish, every OpenRouter call bills the account you chose, and each teammate role runs the model you picked for it.

A workspace is one OpenRouter account and its settings.
It sets which key every call bills to, plus optional models and env.
`default` always exists.

## Commands

```bash
compose workspace                         # list (* = active, keys as their last 4 characters) and the active models
compose workspace personal                # switch; run and verify print `workspace <name>` first
pbpaste | compose workspace add client-x  # create one with the key on the clipboard
pbpaste | compose workspace key client-x  # set or rotate its key; add --linear for its Linear key
compose workspace remove client-x         # delete; removing the active one switches to default
```

From Claude Code, run `/compose:workspace`, `/compose:workspace personal`, or `/compose:workspace add client-x`.
The slash command never asks for a key in chat.
Type `! pbpaste | compose workspace key <name>` instead.

- Keys come from piped stdin or a hidden prompt, and never from an argument.
- A workspace added without a key stops every command while it is active, so nothing bills another account.
- Names are letters, digits, `-`, and `_`.
  The names `add`, `key`, `remove`, and `default` are reserved.

## Config

The commands edit `~/.compose/config.json` (mode 600).
The active workspace is merged over the top level:

```json
{"workspace": "work",
 "models": {"implementer": "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast",
            "fallback": null, "fix": "<default: implementer>",
            "crew": {"planner": {"model": "pi:openai/gpt-6-astra", "effort": "high",
                                 "fallback": [{"model": "claude:claude-opus-5-5", "effort": "high"}]},
                     "groundwork": "claude:claude-opus-5-5", "default": "claude:claude-sonnet-5-5", "small": "claude:claude-haiku-5-5"}},
 "env": {"TYPESAFE_API_KEY": "<any env var the CLI and its tools read>"},
 "workspaces": {"work": {"openrouter_api_key": "sk-or-..."},
                "personal": {"openrouter_api_key": "sk-or-...", "linear_api_key": "lin_api_..."}}}
```

The workspace key reaches pi, OpenCode, the Mercury review, and jev, so every OpenRouter call bills that account.
OpenRouter presets belong to an account, so create `glm-5-3-flash-fast` in each workspace's account.
`run` and `resume` send each model one tiny prompt first.
If an id or preset is wrong, the run stops with the provider's message.

A model id names its harness:

| Id | Runs |
|---|---|
| `pi:<provider/model>` | pi |
| `claude:<model-id>` | Claude Code with that model |
| `claude` | Claude Code with its default model |
| anything else | OpenCode |

## Linear key

A workspace's `linear_api_key` lets the CLI keep Linear's states true.
It moves tasks to In Progress and In Review, rolls up the stories and the feature, and moves the feature to In Review on verify PASS.
Without the key, the CLI prints one `linear skipped` line and carries on.
A Linear error never stops a run.

## Crew models

`models.crew` picks each teammate's model by role, then `default`.

- An entry is a model id, or `{"model": ..., "effort": "high"}`.
  The second form sets Claude Code's `--effort`, or pi's `--thinking` for a `pi:` model.
- An entry may carry a `fallback`, which is another entry or an ordered list.
- `crew start` probes the model it would start on, then each fallback in turn, once a day each.
  It takes the first one that answers and prints which one and why.
  When none answers, it stops before opening a tab and names each model with the error its probe got.
- The team lead's model is the `orchestrator` entry, else `default`.
  It delegates, so it never uses `planner`.
  The wayfinder uses `planner` when it has no entry.
  Groundwork and test-writing teammates use `groundwork`.
  The designer uses `designer`, Opus 5.5 at high effort when the entry is missing.
  Builders and `design-review` use `design`, else `default`.
  A role with no entry falls to the entry named by its first word (`design-003` to `design`).
- `crew start --model small` overrides the role.
  The value can be any name under `models.crew`, or a `claude:<model-id>`.

Teammate sessions run in pi or Claude Code, so an OpenCode id under `models.crew` stops `crew start`.
A pi teammate session loads this repo as its skill but not Claude Code's plugin hooks, so the team lead's edit guard does not apply to it.

## Billing halts

Any provider can answer "payment required".
That includes OpenRouter, Cerebras or Groq through OpenCode, TypeSafe, and jev's own calls.
When one does, `run` and `verify` halt, and three things follow:

- No attempt is consumed and nothing is retried.
- Running tasks finish and no new task starts.
- The banner names the provider, quotes its message, and prints the top-up link.
  The exit code is 3.

After topping up, run `compose resume --project <name>`.
Passed tasks keep their branches.
A halted verify reruns from its first stage.
`COMPOSE_FAKE_402=openrouter` simulates a halt for testing.
