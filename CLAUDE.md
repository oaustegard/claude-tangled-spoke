# Claude Tangled Spoke

This repo is the **hub** — it configures your Claude Code on the Web session
with authenticated access to [Tangled](https://tangled.org), the federated
git host built on ATProto.

## What this gives you

After `SessionStart`, you have:

- `tg` CLI on `$PATH`, already logged into the user's PDS
- Read-only `git clone https://tangled.org/...` (HTTPS) works out of the box
- No SSH plumbing — see "CCotw networking quirk" below for why

## Hub/spoke model

- **Hub** (this repo): boots the session, installs `tg`, authenticates
- **Spokes** (Tangled repos): where actual work happens

```bash
# Read paths — work anonymously, no auth needed
tg repo list <handle>
tg repo view <owner>/<name>
tg issue list --repo <owner>/<name>
tg pr list --repo <owner>/<name>
tg pr view --repo <owner>/<name> <rkey>
tg pr patch --repo <owner>/<name> <rkey>    # prints the latest round's diff

# Write paths — need a logged-in session (boot.sh handles this)
tg issue create  --repo <owner>/<name> --title "..." --body "..."
tg issue comment --repo <owner>/<name> <rkey> --body "..."
tg issue close   --repo <owner>/<name> <rkey>
tg pr comment    --repo <owner>/<name> <rkey> --body "..."
tg pr create     --repo <owner>/<name> --from <branch> --base main --title "..."
tg ssh-key add ~/.ssh/id_ed25519.pub --name <label>
```

### About identifiers — rkeys, not numbers

`tg` reads issues and PRs through the **Constellation** backlink index, which
indexes ATProto records directly off PDSes. That layer gives us rkeys (the
13-char trailing path segment of an at-uri) but not the sequential issue/PR
*numbers* you see in Tangled's web UI — those are assigned by **AppView**
when it ingests records into its own database. There can be a noticeable lag
between record creation and AppView ingestion (sometimes hours; sometimes
records appear not to get numbered at all if AppView filters them).

Implication for `tg`:

- We display the rkey, e.g. `3mkux6xc5n22k`. It's stable, durable, and unique.
- We do NOT display anything like `#3`. Earlier versions did — that was a
  local Python `enumerate()` counter from whatever Constellation happened to
  return in this session, never anything Tangled itself uses. The web URL
  pattern `tangled.org/<owner>/<repo>/issues/<N>` takes the AppView number,
  not the rkey, so rkey-based URLs don't resolve.
- To find the canonical issue/PR number on the web, browse
  `tangled.org/<owner>/<repo>/issues` once AppView has caught up.

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
- `boot.sh` does not install or touch SSH keys. If you need to push to
  Tangled from a machine with SSH egress, manage `~/.ssh` yourself there
  and register the public key once via `tg ssh-key add ~/.ssh/id_ed25519.pub`.

## What's NOT here (use the Tangled web UI)

- **PR merge / close / reopen** — `sh.tangled.repo.pull.status` records can
  be written, but AppView ingestion of those records is known-broken (see
  [tang issue #2](https://tangled.org/onev.cat/tang/issues/2)). The web UI
  remains the canonical place to merge.
- **PR checkout** — straightforward `git fetch` of the source branch, but
  only works for branch-based PRs (not patch-only ones).

## CCotw networking quirk: SSH egress is blocked

CCotw containers reach tangled.org on 443 (HTTPS) but **not on port 22**.
This is a blanket Anthropic egress rule — `github.com:22` and
`gitlab.com:22` are blocked too, not just Tangled. Since `git push` to
Tangled requires SSH, **`boot.sh` does not set up SSH at all**: previous
versions installed a key and a global `url.git@tangled.org:.insteadOf
https://tangled.org/` rule that actively broke read-only HTTPS clones
(the rewrite forced every clone through port 22, which then failed).
`boot.sh` now also defensively removes that rule from `--global` config on
every run, so containers that were provisioned by an older boot get
healed on their next session start.

Net effect of the current boot:

- ✓ `tg repo list/view/create/clone` — fine (all HTTPS/XRPC)
- ✓ `tg issue/pr` reads and writes — fine (XRPC to PDS)
- ✓ `git clone https://tangled.org/...` — fine (read-only HTTPS, no
  `insteadOf` rewrite in the way)
- ✓ `tg pr create` — uploads the patch as a PDS blob, no push needed; this
  is the in-session contribution path
- ✓ `tg repo create --source <url>` — **the knot pulls from the URL**
  server-side over HTTPS, no SSH required from CCotw
- ✗ `git push` to a Tangled remote from CCotw — fails (port 22 blocked);
  do branch-based pushes from a machine with SSH egress instead

For populating a Tangled repo from CCotw, use `--source`:

```bash
tg repo create my-mirror --source https://github.com/me/my-repo.git
```

For ongoing pushes after creation, do them from a machine with SSH egress
(your laptop or a GitHub Action with an SSH key secret). Register the
public key once via `tg ssh-key add ~/.ssh/id_ed25519.pub` from any
authenticated session.

### Upstream bug to know about

`sh.tangled.repo.delete` cleans up `repo_keys` but not `repo_aliases`. After
a delete, recreating with the same name leaves the new bare repo orphaned
(reachable on disk at `scanPath/<new-repoDid>` but not findable via the
HTTP routing). Workaround: pick a fresh name. See the issue we filed
upstream against `tangled.org/tangled.org/core`.
