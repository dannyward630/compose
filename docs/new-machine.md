# Set up a new machine

One command takes a Mac to a working `compose` install:

```sh
curl -fsSL https://raw.githubusercontent.com/prodoxx/compose/main/bin/install.sh | sh
```

It runs on macOS only.
It clones `compose` into `~/.compose/src` (set `COMPOSE_INSTALL_DIR` for another place), or reuses the checkout your `~/.claude/skills/compose` link already points to.
It links `~/.local/bin/compose` and `~/.claude/skills/compose`, installs uv when it is missing, and starts `compose setup`.
It never edits your shell profile.
Setup stops when it finds a fast-coding install, and points to the migration at the end of this page.
[requirements.md](requirements.md) explains what each tool is for.

## What setup does

On a terminal, `compose setup` is a guided screen where you can skip any step.
With `--yes`, or without a terminal, it takes every default through a plain path and never prompts.
A key you did not enter is skipped, and the ending lists it with the command that sets it later.
Setup never installs Claude Code.
Without `claude` on the PATH it runs every step that does not need it, skips the rest, and ends by printing the Claude Code install line and asking you to run `compose setup` again.

| Step group | Level | What setup does | Needs Claude Code |
|---|---|---|---|
| git, Node, gh, gh stack | required | git comes from `xcode-select --install` (setup only reports it); installs `node` and `gh` with Homebrew and the `gh stack` extension; asks you to run `gh auth login` | no |
| claude | required | reports it only, with its install line | no |
| herdr | required | installs herdr with its own installer and the herdr skill file | no |
| pi | required | installs pi with `npm install -g --ignore-scripts`, and declares its `openrouter-fast` provider in `~/.pi/agent/models.json` with no key in it | no |
| Links | required | links `compose` into `~/.local/bin` and the skill into `~/.claude/skills`; reports when `~/.local/bin` is not on your PATH | no |
| Keys | required | saves the OpenRouter key, the TypeSafe key, and the Linear key into `~/.compose/auth.json` | the Linear connector check only |
| i-have-adhd skill | required | adds the marketplace | yes |
| Homebrew, uv, jev | default | installs Homebrew when missing, uv, and the `jev/` environment | no |
| trail, treehouse | default | installs `@trailhq/trail-code` and treehouse | no |
| bp, Chromium | default | links `bp` into `~/.local/bin` and installs Playwright's Chromium | no |
| herdr config, herdr pi integration | default | writes herdr's config (below) and installs herdr's pi integration | no |
| Models and `.env` | default | adds the default model choices to `~/.compose/config.json` and the `TEXT_MODEL` lines to `~/.compose/.env`, never overwriting what is there | no |
| git rerere | default | sets `rerere.enabled` globally when it is unset | no |
| superpowers, herdr claude integration | default | installs the superpowers plugin and herdr's claude integration | yes |
| Framelink | opt-in, designer | adds the `framelink-figma` MCP server and your Figma token, for the designer only | yes |

Setup ends with a model probe against `models.implementer`, unless you skipped the OpenRouter key or ran with `--yes`.
It exits 1 when the probe fails, and prints how to create the OpenRouter preset `glm-5-3-flash-fast` and where to change the model (`models.implementer` in `~/.compose/config.json`).
`compose doctor` shows the same steps, with one `MISSING` line per gap.

On the plain path, setup ends with `compose is ready`, or with `compose is installed but not ready:` and one line per missing required step.
Then it tells you the next move: `compose` outside herdr, or `claude` in a pane and `/compose` inside it.

## herdr settings

A machine without a herdr config gets the config the maintainer uses, from `setup/herdr.toml` in the checkout.
A machine with one keeps all of it, and setup sets only the two lines `compose` needs, so the only desktop alert is the one `compose` sends itself:

```toml
[ui.toast]
delivery = "off"

[ui.sound]
enabled = false
```

A config that is a symlink or not writable is left alone, and setup prints the two lines for you to set.
`compose doctor` warns while either one is on.

## Each repo

A repo needs no setup ahead of time.
The first run in a repo asks for its Linear project and writes `.compose/linear.json`, which stays out of git.

## Update

Run the install command again: it pulls the checkout with `--ff-only`, relinks the CLI and the skill, and runs `compose setup`, which skips what is already done.
Or run `compose update`: it pulls with `--ff-only`, relinks what `compose` owns (the CLI, the skill, and `bp`), and runs `compose doctor`.
`compose update` stops when the checkout has local changes.
After an update, restart any long-running `compose watch` or `status --watch`, because it keeps running the code it started with.

## Move a machine from fast-coding

A machine set up before the rename has `fast-coding` links and `~/.fast-coding/`.
Run the migration with the old checkout's path; it points the checkout at `prodoxx/compose`, pulls, moves `~/.fast-coding/` to `~/.compose/`, and swaps both links:

```sh
curl -fsSL https://raw.githubusercontent.com/prodoxx/compose/main/bin/migrate-to-compose.sh | bash -s -- ~/code/fast-coding
```

It is safe to run again, and it prints the few steps left by hand, starting with restarting Claude Code so `/compose:*` replaces `/fast-coding:*`.
