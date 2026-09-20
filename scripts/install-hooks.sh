#!/usr/bin/env bash
#
# scripts/install-hooks.sh -- install this repository's git hooks.
#
# Hooks are NOT shared by git: `.git/hooks` is never cloned, checked out or
# merged, so a hook committed to the tree does nothing until someone installs
# it. That is why this is a script you run once, per clone, on purpose --
# and why the README has to tell you to.
#
# It is opt-in by design. Nothing else in this repository installs a hook
# behind your back; a checkout that silently starts running code on commit is
# a worse problem than an unchecked commit.
#
# Installed:
#   pre-commit -> scripts/check.sh --fast   (frontend, no Docker, ~20 s)
#
# Usage:
#   bash scripts/install-hooks.sh              # install (refuses to clobber)
#   bash scripts/install-hooks.sh --force      # overwrite a foreign hook
#   bash scripts/install-hooks.sh --uninstall  # remove the hooks it installed
#   bash scripts/install-hooks.sh --status     # report what is installed

set -uo pipefail

to_host_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(to_host_path "$(cd "$SCRIPT_DIR/.." && pwd)")"
SOURCE_DIR="$REPO_ROOT/scripts/hooks"

# A marker line the installed copy carries, so --uninstall and --status can
# tell "our hook" from one someone else (or another tool) put there.
MARKER="# solver-hook: installed by scripts/install-hooks.sh"

HOOKS=(pre-commit)

MODE="install"
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)     FORCE=1 ;;
    --uninstall) MODE="uninstall" ;;
    --status)    MODE="status" ;;
    -h|--help)   sed -n '/^# Usage:$/,/--status/p' "$0" | sed 's/^#\{1,\} \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# In a worktree, `.git` is a file and the hooks directory is the shared one in
# the main checkout -- so installing from a worktree installs for every
# worktree at once. `git rev-parse --git-path hooks` resolves that correctly;
# `$REPO_ROOT/.git/hooks` does not.
HOOK_DIR="$(to_host_path "$(git -C "$REPO_ROOT" rev-parse --git-path hooks 2>/dev/null)")"
if [[ -z "$HOOK_DIR" ]]; then
  echo "not a git repository: $REPO_ROOT" >&2
  exit 1
fi
# `--git-path` can return a path relative to the repository root.
case "$HOOK_DIR" in
  /*|[A-Za-z]:/*) ;;
  *) HOOK_DIR="$REPO_ROOT/$HOOK_DIR" ;;
esac

CONFIGURED_PATH="$(git -C "$REPO_ROOT" config --get core.hooksPath 2>/dev/null)"
if [[ -n "$CONFIGURED_PATH" ]]; then
  echo "note: core.hooksPath is set to '$CONFIGURED_PATH'; git will run hooks"
  echo "      from there. Installing into $HOOK_DIR anyway."
fi

case "$MODE" in

  status)
    for hook in "${HOOKS[@]}"; do
      target="$HOOK_DIR/$hook"
      if [[ ! -e "$target" ]]; then
        echo "$hook: not installed"
      elif grep -qF "$MARKER" "$target" 2>/dev/null; then
        echo "$hook: installed (solver)"
      else
        echo "$hook: installed, but NOT by this script -- left alone"
      fi
    done
    ;;

  uninstall)
    for hook in "${HOOKS[@]}"; do
      target="$HOOK_DIR/$hook"
      if [[ ! -e "$target" ]]; then
        echo "$hook: not installed, nothing to do"
      elif grep -qF "$MARKER" "$target" 2>/dev/null; then
        rm -f "$target"
        echo "$hook: removed"
      else
        echo "$hook: not ours (no marker) -- left alone" >&2
      fi
    done
    ;;

  install)
    mkdir -p "$HOOK_DIR" || exit 1
    status=0
    for hook in "${HOOKS[@]}"; do
      source="$SOURCE_DIR/$hook"
      target="$HOOK_DIR/$hook"

      if [[ ! -f "$source" ]]; then
        echo "$hook: $source is missing" >&2
        status=1
        continue
      fi

      if [[ -e "$target" ]] && ! grep -qF "$MARKER" "$target" 2>/dev/null && [[ $FORCE -eq 0 ]]; then
        echo "$hook: a hook is already installed that this script did not write." >&2
        echo "      Not overwriting it. Inspect $target, then re-run with --force." >&2
        status=1
        continue
      fi

      # Copied, not symlinked: symlinks need Developer Mode or an elevated
      # shell on Windows, and a hook that fails to install on the one platform
      # this is developed on is not a hook. The cost is that changing
      # scripts/hooks/pre-commit means re-running this script -- which the
      # header line below reminds you of every time the hook runs.
      {
        head -n 1 "$source"
        printf '%s\n' "$MARKER"
        printf '%s\n' "# Re-run scripts/install-hooks.sh after editing scripts/hooks/$hook."
        tail -n +2 "$source"
      } > "$target" || { status=1; continue; }
      chmod +x "$target" 2>/dev/null
      echo "$hook: installed -> $target"
    done
    if [[ $status -eq 0 ]]; then
      echo
      echo "Done. Every commit now runs scripts/check.sh --fast."
      echo "Skip one commit with: git commit --no-verify"
      echo "Remove with:          bash scripts/install-hooks.sh --uninstall"
    fi
    exit $status
    ;;
esac
