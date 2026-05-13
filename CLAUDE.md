# Claude Tangled Spoke

This repo is the **hub** — it configures your Claude Code on the Web session
with authenticated access to [Tangled](https://tangled.org), the federated
git host built on ATProto.

## What this gives you

After `SessionStart`, you have:

- `git` over SSH to `tangled.org` (clone, push, pull) — assuming a key was
  provisioned. https://tangled.org/... URLs are rewritten to SSH via
  `git config --global url.git@tangled.org:.insteadOf https://tangled.org/`
- `tg` CLI on `$PATH`, already logged into the user's PDS

## Hub/spoke model

- **Hub** (this repo): boots the session, installs `tg`, authenticates
- **Spokes** (Tangled repos): where actual work happens

```bash
# Read paths — work anonymously, no auth needed
tg repo list <handle>
tg repo view <owner>/<name>
tg issue list --repo <owner>/<name>
tg pr list --repo <owner>/<name>
tg pr view --repo <owner>/<name> <#n>
tg pr patch --repo <owner>/<name> <#n>      # prints the latest round's diff

# Write paths — need a logged-in session (boot.sh handles this)
tg issue create  --repo <owner>/<name> --title "..." --body "..."
tg issue comment --repo <owner>/<name> <#n> --body "..."
tg issue close   --repo <owner>/<name> <#n>
tg pr comment    --repo <owner>/<name> <#n> --body "..."
tg pr create     --repo <owner>/<name> --from <branch> --base main --title "..."
tg ssh-key add ~/.ssh/id_ed25519.pub --name <label>
```

### Spoke clone convention: `.spokes/`

**Always clone spoke repos to `./.spokes/<repo-name>` inside this workspace,
not to `/tmp/` or `/home/user/`.** The directory is gitignored, so spoke
checkouts never pollute the hub's git state.

```bash
tg repo clone <owner>/<name> .spokes/<name>
cd .spokes/<name>
```

## How `tg` works (read before editing)

`tg` is a single-file stdlib-only Python script at `bin/tg`. It talks to
three Tangled subsystems:

1. **PDS** — each handle's personal data server (resolved via the DID
   document, never hard-coded). All auth, record reads/writes, and blob
   uploads go through standard ATProto XRPC.
2. **Constellation** (default `https://constellation.microcosm.blue`) — the
   backlink index. Used to list issues/PRs *attached to* a repo URI without
   crawling every PDS. The endpoint is *not* XRPC; it's a plain
   `GET /links?target=...&collection=...&path=...`.
3. **Knot** (default `knot1.tangled.sh`, surfaced as `tangled.org` for clone
   URLs) — git server. `tg` currently shells out to `git` for clones and
   bypasses Knot for PR creation (uploads the patch as a PDS blob instead).
   The missing pieces (repo create, PR merge, branch checkout from a PR) all
   need Knot service-auth tokens.

The full NSID list is at the top of `bin/tg`. Wire-format quirk: state
values like `sh.tangled.repo.issue.state.closed` need to be normalized to
bare `closed` for display — see `_normalize_state`.

## When extending `tg`, follow TDD

The repo ships tests in `tests/test_tg.py` covering helpers and mocked
XRPC paths. Run them:

```bash
python3 tests/test_tg.py
```

Add a test for every new helper and every new subcommand. Mock
`constellation_links`, `get_record`, `list_records`, and the `Session`
storage path — never call live Tangled from tests.

## Why deny the MCP GitHub server?

Claude Code's built-in MCP GitHub server is GitHub-only and only sees this
hub repo. This session is Tangled-shaped, so the MCP isn't useful here —
denying it (`.claude/settings.json`) keeps Claude from reaching for it.

## Auth security notes

- The `.env` file is gitignored. Never commit it.
- `ATPROTO_APP_PASSWORD` is an **app password**, not the main account
  password. App passwords are scoped and revocable from
  https://bsky.app/settings/app-passwords (or the tngl.sh equivalent).
- The session JWT is stored at `~/.config/tg/session.json` with mode `0600`.
  It's regenerated each session by `boot.sh`, so the stored copy is
  ephemeral — no long-lived secret on disk.
- The SSH private key, if used, lands at `~/.ssh/id_ed25519` (mode `0600`).
  Source it from `$TANGLED_SSH_KEY` or `$PROJECT_DIR/.ssh/id_ed25519`.

## What's NOT here (use the Tangled web UI)

- **Repo create** — needs `getServiceAuth` against the chosen Knot, then a
  `sh.tangled.repo.create` call on the knot. Two-step flow not yet wired.
- **PR merge / close / reopen** — `sh.tangled.repo.pull.status` records can
  be written, but AppView ingestion of those records is known-broken (see
  [tang issue #2](https://tangled.org/onev.cat/tang/issues/2)). The web UI
  remains the canonical place to merge.
- **PR checkout** — straightforward `git fetch` of the source branch, but
  only works for branch-based PRs (not patch-only ones).
