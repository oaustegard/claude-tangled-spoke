#!/usr/bin/env bash
# Bootstrap `tg` for a Claude skill invocation.
#
# 1. Put the vendored `bin/tg` on $PATH (symlink into /usr/local/bin).
# 2. Map BSKY_HANDLE / BSKY_APP_PASSWORD → ATPROTO_HANDLE / ATPROTO_APP_PASSWORD
#    (claude.ai and CCotw provision the BSKY_* names; tg itself reads ATPROTO_*).
#    ATPROTO_* wins if both are set.
# 3. Run `tg auth login` only when there is no live session.
#
# Idempotent — safe to call before every `tg …` invocation.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This script lives at <root>/skills/tg/auth.sh.
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TG_BIN="$ROOT_DIR/bin/tg"

if [ ! -x "$TG_BIN" ]; then
    echo "tg-skill: $TG_BIN not found or not executable" >&2
    exit 1
fi

if ! command -v tg >/dev/null 2>&1; then
    mkdir -p /usr/local/bin 2>/dev/null || true
    ln -sf "$TG_BIN" /usr/local/bin/tg 2>/dev/null \
        || sudo ln -sf "$TG_BIN" /usr/local/bin/tg
fi

if tg auth status >/dev/null 2>&1; then
    tg auth status
    exit 0
fi

: "${ATPROTO_HANDLE:=${BSKY_HANDLE:-}}"
: "${ATPROTO_APP_PASSWORD:=${BSKY_APP_PASSWORD:-}}"

if [ -z "${ATPROTO_HANDLE:-}" ] || [ -z "${ATPROTO_APP_PASSWORD:-}" ]; then
    echo "tg-skill: need ATPROTO_HANDLE / ATPROTO_APP_PASSWORD (or BSKY_HANDLE / BSKY_APP_PASSWORD)" >&2
    exit 1
fi

export ATPROTO_HANDLE ATPROTO_APP_PASSWORD
tg auth login --handle "$ATPROTO_HANDLE" <<< "$ATPROTO_APP_PASSWORD"
