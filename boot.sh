#!/bin/bash
# Boot hook for Claude Code on the Web.
# Wires SSH so `git clone/push/pull` against Tangled Just Works, installs the
# bundled `tg` CLI, and logs into the user's PDS with their app password.
#
# Required env (from .env, gitignored):
#   ATPROTO_HANDLE       — e.g. alice.bsky.social or alice.tngl.sh
#   ATPROTO_APP_PASSWORD — app password from Bluesky settings (NOT main password)
#
# Optional env:
#   TANGLED_SSH_KEY      — full SSH private key (PEM). If unset, boot looks for
#                          $PROJECT_DIR/.ssh/id_ed25519.
#   GH_TOKEN             — only used for fetching the spoke template from a
#                          GitHub mirror; not required.

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

# ── SSH setup ──
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# Pin tangled.org's host key so first push doesn't prompt. We pull it live
# instead of hard-coding so a future host key rotation doesn't brick the boot.
if [ ! -s ~/.ssh/known_hosts ] || ! grep -q '^tangled\.org ' ~/.ssh/known_hosts; then
    ssh-keyscan -t ed25519,rsa tangled.org 2>/dev/null >> ~/.ssh/known_hosts || true
fi
chmod 600 ~/.ssh/known_hosts 2>/dev/null || true

KEYFILE=~/.ssh/id_ed25519
if [ -n "${TANGLED_SSH_KEY:-}" ]; then
    printf '%s\n' "$TANGLED_SSH_KEY" > "$KEYFILE"
    chmod 600 "$KEYFILE"
    summary "✓ SSH key installed from TANGLED_SSH_KEY"
elif [ -f "$PROJECT_DIR/.ssh/id_ed25519" ]; then
    cp "$PROJECT_DIR/.ssh/id_ed25519" "$KEYFILE"
    chmod 600 "$KEYFILE"
    summary "✓ SSH key installed from $PROJECT_DIR/.ssh/id_ed25519"
else
    summary "⚠ No SSH key found — git push to Tangled will fail until one is added"
fi

# Map https://tangled.org/... clone URLs to ssh, so `git clone https://...` works.
git config --global "url.git@tangled.org:.insteadOf" "https://tangled.org/" 2>/dev/null || true

# ── Install tg ──
TG_BIN="$PROJECT_DIR/bin/tg"
if [ -x "$TG_BIN" ]; then
    mkdir -p /usr/local/bin 2>/dev/null || true
    ln -sf "$TG_BIN" /usr/local/bin/tg 2>/dev/null || sudo ln -sf "$TG_BIN" /usr/local/bin/tg
    summary "✓ tg linked from $TG_BIN"
else
    summary "⚠ $TG_BIN not found — `tg` CLI unavailable"
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
    summary "⚠ ATPROTO_HANDLE or ATPROTO_APP_PASSWORD missing — `tg` will be unauthenticated"
fi

# ── Print summary into Claude's context ──
echo "── claude-tangled-and-spoke boot ──"
for line in "${SUMMARY_LINES[@]}"; do echo "  $line"; done
echo ""
echo "Try:  tg auth status   |   tg repo list   |   tg --help"
