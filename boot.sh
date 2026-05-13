#!/bin/bash
# Boot hook for Claude Code on the Web.
# Installs the bundled `tg` CLI and logs into the user's PDS with their app
# password. SSH/git-push plumbing is intentionally absent: CCotw blocks
# outbound port 22, and Tangled contributions can happen patch-based via
# `tg pr create` (which uploads the patch as a PDS blob). For branch-based
# PRs that need a real push, do it from a machine with SSH egress.
#
# Required env (from .env, gitignored):
#   ATPROTO_HANDLE       — e.g. alice.bsky.social or alice.tngl.sh
#   ATPROTO_APP_PASSWORD — app password from Bluesky settings (NOT main password)

set -e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SUMMARY_LINES=()
summary() { SUMMARY_LINES+=("$1"); }

# ── Source credentials ──
for envfile in "$PROJECT_DIR"/.env "$PROJECT_DIR"/*.env /mnt/project/*.env; do
    [ -f "$envfile" ] || continue
    set -a; . "$envfile" 2>/dev/null || true; set +a
done

# ── Wait for network ──
for i in 1 2 3 4; do
    curl -sf --max-time 5 -o /dev/null "https://tangled.org" && break
    sleep $((i * 2))
done

# ── Strip legacy git config that breaks HTTPS clones ──
# Pre-45bc234 boots installed `url.git@tangled.org:.insteadof=https://tangled.org/`
# globally to force pushes over SSH. CCotw blocks port 22, so the rewrite turns
# every read-only clone into a failing SSH attempt. Remove it if present.
git config --global --unset-all url.git@tangled.org:.insteadof 2>/dev/null || true

# ── Install tg ──
TG_BIN="$PROJECT_DIR/bin/tg"
if [ -x "$TG_BIN" ]; then
    mkdir -p /usr/local/bin 2>/dev/null || true
    ln -sf "$TG_BIN" /usr/local/bin/tg 2>/dev/null || sudo ln -sf "$TG_BIN" /usr/local/bin/tg
    summary "✓ tg linked from $TG_BIN"
else
    summary "⚠ $TG_BIN not found — 'tg' CLI unavailable"
fi

# ── Auth login ──
if [ -n "${ATPROTO_HANDLE:-}" ] && [ -n "${ATPROTO_APP_PASSWORD:-}" ]; then
    if command -v tg >/dev/null && tg auth login --handle "$ATPROTO_HANDLE" >/dev/null 2>&1 <<< "$ATPROTO_APP_PASSWORD"; then
        WHO=$(tg auth status 2>/dev/null | head -1 | sed 's/^Handle: //')
        summary "✓ Logged in as $WHO"
    else
        summary "⚠ tg auth login failed — check ATPROTO_HANDLE/ATPROTO_APP_PASSWORD"
    fi
else
    summary "⚠ ATPROTO_HANDLE or ATPROTO_APP_PASSWORD missing — 'tg' will be unauthenticated"
fi

# ── Print summary into Claude's context ──
echo "── claude-tangled-spoke boot ──"
for line in "${SUMMARY_LINES[@]}"; do echo "  $line"; done
echo ""
echo "Try:  tg auth status   |   tg repo list   |   tg --help"
