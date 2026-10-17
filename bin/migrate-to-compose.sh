#!/usr/bin/env bash
# migrate-to-compose.sh - move a machine's fast-coding install over to compose.
#
# Usage: bash bin/migrate-to-compose.sh <checkout>
#   or, on a machine whose checkout still has the old code:
#   curl -fsSL https://raw.githubusercontent.com/prodoxx/compose/main/bin/migrate-to-compose.sh | bash -s -- <checkout>
#   <checkout> is the existing fast-coding or compose checkout, e.g. ~/code/fast-coding
#
# Idempotent: every step checks the current state first, so running it again
# after a partial or full run only does what is still left.

set -euo pipefail

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
did()  { printf '  done  %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

[ $# -eq 1 ] || die "usage: $0 <checkout>"
[ -d "$1" ] || die "checkout not found: $1"
CHECKOUT="$(cd "$1" && pwd -P)"

# --- 0. checkout: point it at prodoxx/compose and bring it up to date ------
say "0. checkout"
url="$(git -C "$CHECKOUT" remote get-url origin 2>/dev/null || true)"
case "$url" in
  *prodoxx/fast-coding*)
    git -C "$CHECKOUT" remote set-url origin "${url/prodoxx\/fast-coding/prodoxx/compose}"
    did "origin $url -> $(git -C "$CHECKOUT" remote get-url origin)" ;;
  *prodoxx/compose*) ok "origin is $url" ;;
  *) say "  warn  origin is '$url', not prodoxx/compose; left as is" ;;
esac
if [ ! -x "$CHECKOUT/bin/compose" ]; then
  [ -z "$(git -C "$CHECKOUT" status --porcelain --untracked-files=no)" ] \
    || die "$CHECKOUT has uncommitted changes; commit or set them aside, then rerun"
  [ "$(git -C "$CHECKOUT" rev-parse --abbrev-ref HEAD)" = main ] \
    || die "$CHECKOUT is not on main; check out main, then rerun"
  git -C "$CHECKOUT" pull -q --ff-only origin main
  did "pulled main into $CHECKOUT"
else
  ok "$CHECKOUT already has bin/compose"
fi
say ""

# --- preflight: the checkout must now be the renamed code ------------------
[ -x "$CHECKOUT/bin/compose" ] || die "$CHECKOUT/bin/compose is missing or not executable - is the checkout on the merged rename?"
[ -f "$CHECKOUT/.claude-plugin/plugin.json" ] || die "$CHECKOUT/.claude-plugin/plugin.json is missing"
grep -q '"name": *"compose"' "$CHECKOUT/.claude-plugin/plugin.json" \
  || die "$CHECKOUT/.claude-plugin/plugin.json does not name the plugin compose"
[ -f "$CHECKOUT/SKILL.md" ] || die "$CHECKOUT/SKILL.md is missing"

OLD_STATE="$HOME/.fast-coding"
NEW_STATE="$HOME/.compose"
OLD_BIN="$HOME/.local/bin/fast-coding"
NEW_BIN="$HOME/.local/bin/compose"
OLD_SKILL="$HOME/.claude/skills/fast-coding"
NEW_SKILL="$HOME/.claude/skills/compose"

say "compose checkout: $CHECKOUT"
say ""

# --- 1. state dir: ~/.fast-coding -> ~/.compose ---------------------------
say "1. state dir"
if [ -e "$OLD_STATE" ] || [ -L "$OLD_STATE" ]; then
  if [ -e "$NEW_STATE" ] || [ -L "$NEW_STATE" ]; then
    die "both $OLD_STATE and $NEW_STATE exist; refusing to merge them. Compare them by hand, keep one, and rerun."
  fi
  mv "$OLD_STATE" "$NEW_STATE"
  did "moved $OLD_STATE -> $NEW_STATE"
elif [ -d "$NEW_STATE" ]; then
  ok "$NEW_STATE already in place"
else
  ok "neither $OLD_STATE nor $NEW_STATE exists; nothing to move (compose creates $NEW_STATE when needed)"
fi

# Replace a symlink only if it is a symlink (never clobber a real file or dir).
# $1 = link path, $2 = desired target
ensure_link() {
  local link="$1" target="$2"
  if [ -L "$link" ]; then
    if [ "$(readlink "$link")" = "$target" ]; then
      ok "$link -> $target"
      return
    fi
    ln -sfn "$target" "$link"
    did "repointed $link -> $target"
  elif [ -e "$link" ]; then
    die "$link exists and is not a symlink; refusing to replace it"
  else
    mkdir -p "$(dirname "$link")"
    ln -s "$target" "$link"
    did "linked $link -> $target"
  fi
}

# Remove an old symlink. Only symlinks are removed.
remove_old_link() {
  local link="$1"
  if [ -L "$link" ]; then
    rm "$link"
    did "removed old symlink $link (was -> $(printf '%s' "$2"))"
  elif [ -e "$link" ]; then
    die "$link exists and is not a symlink; refusing to remove it - move it aside by hand and rerun"
  else
    ok "$link already gone"
  fi
}

# --- 2. CLI symlink ---------------------------------------------------------
say ""
say "2. CLI on PATH"
ensure_link "$NEW_BIN" "$CHECKOUT/bin/compose"
old_bin_target="$( [ -L "$OLD_BIN" ] && readlink "$OLD_BIN" || true )"
remove_old_link "$OLD_BIN" "$old_bin_target"

# --- 3. skill + plugin symlink ----------------------------------------------
# The plugin is not installed through a marketplace. Claude Code loads any
# directory under ~/.claude/skills that carries .claude-plugin/plugin.json as a
# plugin with the pseudo-marketplace "skills-dir" (it shows up as
# "fast-coding@skills-dir" in ~/.claude.json pluginUsage). So this one symlink
# is the whole plugin registration: once it points at the renamed checkout, the
# plugin loads as compose@skills-dir with commands /compose:yolo etc.
say ""
say "3. skill and plugin directory"
ensure_link "$NEW_SKILL" "$CHECKOUT"
old_skill_target="$( [ -L "$OLD_SKILL" ] && readlink "$OLD_SKILL" || true )"
remove_old_link "$OLD_SKILL" "$old_skill_target"

# --- 4. checks ----------------------------------------------------------------
say ""
say "4. checks"
if command -v compose >/dev/null 2>&1; then
  ok "compose on PATH: $(command -v compose)"
else
  say "  warn  compose is not on PATH - is ~/.local/bin in PATH?"
fi
if command -v fast-coding >/dev/null 2>&1; then
  say "  warn  a fast-coding command is still on PATH: $(command -v fast-coding)"
fi
for f in .env config.json; do
  if [ -f "$NEW_STATE/$f" ]; then ok "$NEW_STATE/$f present"; else say "  warn  $NEW_STATE/$f missing"; fi
done
if env | grep -q '^FAST_CODING_'; then
  say "  warn  FAST_CODING_* variables are set in this shell; rename them to COMPOSE_* in your shell profile:"
  env | grep '^FAST_CODING_' | sed 's/=.*//; s/^/          /'
fi

# --- 5. manual steps (printed, not performed) --------------------------------
cat <<EOF

5. Claude Code plugin - manual steps (nothing below was changed by this script)

   How it is installed: as a skills-dir plugin, not from a marketplace.
   ~/.claude/skills/<name> holds a checkout with .claude-plugin/plugin.json and
   Claude Code loads it as <plugin-name>@skills-dir. It is NOT listed in
   ~/.claude/plugins/installed_plugins.json, known_marketplaces.json,
   marketplaces/, or enabledPlugins in ~/.claude/settings.json, so there is no
   'claude plugin uninstall' / 'install' to run and no settings.json edit.

   a. Restart every running Claude Code session (and herdr agents running
      claude) so they pick up compose@skills-dir. Check with:
        claude plugin list        # expect compose@skills-dir, no fast-coding
      and in a session, /compose:yolo, /compose:planner, /compose:designer and
      /compose:workspace should exist and /fast-coding:* should not.

   b. Optional cleanup of leftovers Claude Code wrote under the old name
      (harmless if left; delete only after a) shows compose loading):
        rmdir ~/.claude/plugins/data/fast-coding-skills-dir   # empty plugin data dir
      ~/.claude.json keeps usage counters under "fast-coding@skills-dir"
      (pluginUsage) and "fast-coding:yolo" (skillUsage); they are stats only.
      Leave them, or remove those two keys with Claude Code closed:
        jq 'del(.pluginUsage["fast-coding@skills-dir"]) | del(.skillUsage["fast-coding:yolo"])' \\
          ~/.claude.json > ~/.claude.json.new && mv ~/.claude.json.new ~/.claude.json

   c. herdr: its workspaces labelled "fast-coding" are named after the repo
      directory ($CHECKOUT), not the tool, so they only change if you rename
      that directory. If you do rename it, rerun this script with the new path
      so both symlinks follow.
EOF

# --- 6. repos with old-name leftovers (listed, not changed) -------------------
say ""
say "6. repos under ~/workspace and ~/code with old-name leftovers (not changed)"
found=0
for root in "$HOME/workspace" "$HOME/code"; do
  [ -d "$root" ] || continue
  while IFS= read -r d; do
    say "  .fast-coding dir: $d   (rename to $(dirname "$d")/.compose if compose should keep its state)"
    found=1
  done < <(find "$root" -maxdepth 6 -type d -name .fast-coding -not -path '*/node_modules/*' 2>/dev/null)
  while IFS= read -r g; do
    r="$(dirname "$g")"
    b="$(git -C "$r" for-each-ref --format='%(refname:short)' 'refs/heads/fast-coding/*' 'refs/remotes/*/fast-coding/*' 2>/dev/null | tr '\n' ' ')"
    if [ -n "$b" ]; then
      say "  fast-coding/* branches in $r: $b"
      found=1
    fi
  done < <(find "$root" -maxdepth 5 -name .git -not -path '*/node_modules/*' 2>/dev/null)
done
[ "$found" -eq 1 ] || ok "none found"

say ""
say "migration finished"
