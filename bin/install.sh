#!/bin/sh
# install.sh - one command installs compose: checkout, links, uv, guided setup.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/prodoxx/compose/main/bin/install.sh | sh
#
# macOS only. Clones https://github.com/prodoxx/compose into the checkout (or
# pulls the one that already exists), links the CLI and the Claude skill into
# place, installs uv when it is missing, then hands over to `compose setup`.

set -eu

say() { printf '%s\n' "$*"; }
ok()  { printf '  ok    %s\n' "$*"; }
did() { printf '  done  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

REPO_URL="https://github.com/prodoxx/compose"
SKILL="$HOME/.claude/skills/compose"
CLI="$HOME/.local/bin/compose"

[ "$(uname -s)" = "Darwin" ] || die "compose installs on macOS only"
command -v git >/dev/null 2>&1 || die "git is required to install compose"
command -v curl >/dev/null 2>&1 || die "curl is required to install compose"

if [ -L "$SKILL" ] && [ -x "$(readlink "$SKILL")/bin/compose" ]; then
  CHECKOUT="$(readlink "$SKILL")"
else
  CHECKOUT="${COMPOSE_INSTALL_DIR:-$HOME/.compose/src}"
fi

if [ -d "$CHECKOUT" ]; then
  git -C "$CHECKOUT" pull --ff-only origin main || say "  warn  git pull failed; going on with the checkout as it is"
  ok "checkout: $CHECKOUT"
else
  git clone "$REPO_URL" "$CHECKOUT"
  did "cloned $REPO_URL into $CHECKOUT"
fi

ensure_link() {
  if [ -L "$1" ]; then
    if [ "$(readlink "$1")" = "$2" ]; then
      ok "$1 -> $2"
    else
      rm "$1"
      ln -s "$2" "$1"
      did "repointed $1 -> $2"
    fi
  elif [ -e "$1" ]; then
    say "  warn  $1 exists and is not a symlink; left as it is"
  else
    mkdir -p "$(dirname "$1")"
    ln -s "$2" "$1"
    did "linked $1 -> $2"
  fi
}

ensure_link "$CLI" "$CHECKOUT/bin/compose"
ensure_link "$SKILL" "$CHECKOUT"

if command -v uv >/dev/null 2>&1; then
  ok "uv: $(command -v uv)"
else
  say "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  PATH="$HOME/.local/bin:$PATH"
  ok "uv installed into $HOME/.local/bin"
fi

if ( : < /dev/tty ) 2>/dev/null; then
  say "starting the guided setup"
  exec "$CHECKOUT/bin/compose" setup < /dev/tty
fi
say "no terminal; running the guided setup with every default"
exec "$CHECKOUT/bin/compose" setup --yes
