# Set up a new machine

This page takes a fresh Mac to a working `compose` install.
It follows [requirements.md](requirements.md), which explains what each tool is for.

## 1. Install the tools

```sh
xcode-select --install                    # git; Python 3.9 ships with macOS
brew install node gh uv                   # Node 22.19+, the GitHub CLI, uv
gh auth login
gh extension install github/gh-stack
git config --global rerere.enabled true
curl -fsSL https://claude.ai/install.sh | bash      # Claude Code, then log in
npm install -g --ignore-scripts @earendil-works/pi-coding-agent   # the default implementer
```

Each optional tool turns on one feature:

| Tool | Install |
|---|---|
| herdr | its installer from [herdr.dev](https://herdr.dev) |
| treehouse | `curl -fsSL https://kunchenguid.github.io/treehouse/install.sh \| sh` |
| graft | `npm i -g @nanonets/graft` |
| Frame0, OpenCode | see [requirements.md](requirements.md#optional) |

## 2. Clone and link `compose`

```sh
git clone https://github.com/prodoxx/compose ~/code/compose
cd ~/code/compose
ln -s "$PWD" ~/.claude/skills/compose
mkdir -p ~/.local/bin && ln -s "$PWD/bin/compose" ~/.local/bin/
ln -s "$PWD/bp/bin/bp.mjs" ~/.local/bin/bp     # the browser driver, optional
```

`bp` also needs Playwright's Chromium: `npx playwright install chromium`.
The skill link is how Claude Code finds the skill, the `/compose:*` commands, and the hooks.
Open Claude Code once and check that `/compose` and its commands appear.

## 3. Install the skills doctor requires

```sh
mkdir -p ~/.claude/skills/herdr && herdr --skill > ~/.claude/skills/herdr/SKILL.md
claude plugin marketplace add ayghri/i-have-adhd
claude plugin install superpowers@claude-plugins-official   # optional, for writing-plans
```

## 4. Add the keys

Keys never go in git or on Linear issues.

- OpenRouter for pi: put the key in `~/.pi/agent/auth.json` under `openrouter` and `openrouter-fast`, declare the `openrouter-fast` provider in `~/.pi/agent/models.json`, and create the `glm-5-3-flash-fast` preset on OpenRouter, as [requirements.md](requirements.md#keys) describes.
- Write `~/.compose/.env` with mode 600, holding `TEXT_MODEL`, `TEXT_MODEL_BASE_URL`, `TEXT_MODEL_API_KEY`, `TEXT_MODEL_REASONING`, `TYPESAFE_API_KEY`, and `TYPESAFE_MODEL`.
- Connect the Linear MCP in Claude Code.
- For the designer only, put a Figma token in `~/.config/figma-context-mcp/.env` and add the `framelink-figma` MCP server as [requirements.md](requirements.md#for-the-designer) shows.

## 5. Copy your settings from an existing machine

Copy these files privately, for example with AirDrop or scp, because they can hold keys.

| File | Holds |
|---|---|
| `~/.compose/config.json` | model choices per role and the [workspaces](workspaces.md) |
| `~/.config/herdr/config.toml` | herdr settings, including the notification setup below |

Keep herdr's own popups and sounds off, so the only desktop alert is the engineering manager's, which `compose` sends itself:

```toml
[ui.toast]
delivery = "off"

[ui.sound]
enabled = false
```

`compose doctor` warns when either one is still on.

## 6. Check the install

```sh
compose doctor                        # one MISSING line per gap, with its install command
uv sync --project ~/code/compose/jev  # the browser agent verify drives
cd ~/code/compose/jev && uv run browser-harness --doctor
```

## Each repo

A repo needs no setup ahead of time.
The first run in a repo asks for its Linear project and writes `.compose/linear.json`, which stays out of git.

## Keep machines in sync

Run `git pull` in `~/code/compose` to update, since both links point into that checkout.
After a pull, restart any long-running `compose watch` or `status --watch`, because it keeps running the code it started with.

## Move a machine from fast-coding

A machine set up before the rename has `fast-coding` links and `~/.fast-coding/`.
Run the migration with the old checkout's path; it points the checkout at `prodoxx/compose`, pulls, moves `~/.fast-coding/` to `~/.compose/`, and swaps both links:

```sh
curl -fsSL https://raw.githubusercontent.com/prodoxx/compose/main/bin/migrate-to-compose.sh | bash -s -- ~/code/fast-coding
```

It is safe to run again, and it prints the few steps left by hand, starting with restarting Claude Code so `/compose:*` replaces `/fast-coding:*`.
