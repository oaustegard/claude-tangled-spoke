# Claude Tangled Spoke

This repo is the **hub** — it configures your Claude Code on the Web session
with authenticated access to [Tangled](https://tangled.org), the federated
git host built on ATProto.

A drop-in analog of [`claude-github-and-spoke`](https://github.com/oaustegard/claude-github-and-spoke)
for the ATProto developer base.

## What this gives you

After session start, your CCotw session has:

- **`tg` CLI** — authenticated against your PDS via an ATProto app password,
  with subcommands for `auth`, `repo`, `issue`, `pr`, and `ssh-key`
- **HTTPS git clone** of any public `tangled.org` repo — `git clone https://tangled.org/<owner>/<name>`
  works read-only; no SSH plumbing in the container (CCotw blocks port 22,
  so SSH wouldn't work anyway — contribute via patch-based PRs with
  `tg pr create`)
- **MCP GitHub server denied** — this session is Tangled-focused; the
  built-in GitHub MCP only sees this hub repo anyway

## The hub/spoke model

- **Hub** (this repo): boots the session, installs `tg`, authenticates
- **Spokes** (your other Tangled repos): where actual work happens

From any session started in this repo, you can:

```bash
# Inspect Tangled state without leaving the terminal
tg auth status
tg repo list                                  # your repos
tg repo list onev.cat                         # someone else's
tg repo view onev.cat/tang
tg issue list --repo onev.cat/tang
tg pr list --repo onev.cat/tang
tg pr view --repo onev.cat/tang 3

# Clone a spoke (always under ./.spokes/ — see below)
tg repo clone onev.cat/tang .spokes/tang      # uses https by default
tg repo clone onev.cat/tang --ssh             # ssh when you need push access

# Open issues, comment on threads, push patch-based PRs
tg issue create --repo myself/proj --title "Bug in X"
tg issue comment --repo myself/proj #3 --body "Fixed in v1.2"
tg pr create   --repo myself/proj --from feature/foo --base main \
                --title "Add foo support"
tg pr comment  --repo myself/proj #1 --body "LGTM"
```

### Spoke clone convention: `.spokes/`

**Always clone spoke repos to `./.spokes/<repo-name>` inside this workspace,
not to `/tmp/` or `/home/user/`.** The directory is gitignored, so spoke
checkouts never pollute the hub's git state. CCotw's git-signing helper also
expects spokes to live under the hub workspace.

## Setup

1. Fork or clone this repo.
2. Create a `.env` file (gitignored) with your ATProto credentials:
   ```
   ATPROTO_HANDLE=alice.bsky.social
   ATPROTO_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
   ```
   Get an app password at https://bsky.app/settings/app-passwords — it's a
   revocable per-app credential, never use your main password.
3. Open the repo in Claude Code on the Web.
4. The `SessionStart` hook runs `boot.sh` automatically.

`boot.sh` does not install SSH keys — CCotw blocks outbound port 22, so a
key there wouldn't help anyway. If you need `git push` to Tangled from a
machine with SSH egress (laptop, GHA runner), manage `~/.ssh` there and
register the public key once via `tg ssh-key add ~/.ssh/id_ed25519.pub`.

## Coverage

| `tg` subcommand                  | Status |
|----------------------------------|--------|
| `auth login/logout/status/refresh/token` | ✓ |
| `repo list/view/clone`           | ✓ |
| `repo create`                    | ✗ (needs Knot service-auth — use web UI) |
| `issue list/view/create/comment` | ✓ |
| `issue close/reopen`             | ✓ (writes state records — AppView ingestion varies, see [tang#2](https://tangled.org/onev.cat/tang/issues/2)) |
| `pr list/view/comment/patch`     | ✓ |
| `pr create` (patch-based)        | ✓ — `git format-patch` + gzip + uploadBlob + putRecord |
| `pr merge/close/checkout`        | ✗ (needs Knot service-auth — use web UI) |
| `ssh-key list/add/delete`        | ✓ |

For the missing pieces — repo creation, PR merge, branch checkout from a PR —
use https://tangled.org directly. The CLI surface here covers the common
read-and-write workflows; the rest depends on Knot service-auth tokens which
are next on the roadmap.

## Architecture notes

`tg` talks to three Tangled subsystems:

1. **PDS** (per-user, resolved from each handle's DID document) — auth,
   record reads/writes, blob uploads. ATProto-standard XRPC.
2. **Constellation** (default `https://constellation.microcosm.blue`) — the
   backlink index. Lists issues/PRs *attached to* a repo URI without needing
   to crawl every PDS.
3. **Knot** (default `knot1.tangled.sh`, served as `tangled.org` for clone
   URLs) — git server. `tg` doesn't talk to Knot directly yet (shells out to
   `git` for clones), but PR creation puts the patch as a blob on the user's
   PDS rather than going through Knot's compare API. This means CCotw-side
   patches work without any service-auth handshake.

The lexicon NSIDs are documented in `bin/tg` near the top.

## Why deny the MCP GitHub server?

Claude Code's built-in MCP GitHub server only sees the hub repo and uses a
GitHub token. This session is Tangled-shaped, so the MCP isn't useful here —
denying it keeps Claude from reaching for it by mistake.

## Hosted on Tangled, mirrored to GitHub

- GitHub: [github.com/oaustegard/claude-tangled-spoke](https://github.com/oaustegard/claude-tangled-spoke) — source of truth
- Tangled: [austegard.com/claude-tangled-spoke-mirror](https://tangled.org/austegard.com/claude-tangled-spoke-mirror) — Tangled mirror, populated server-side from GitHub via the knot's `source` parameter

### How the mirror got there from CCotw (no SSH needed)

Anthropic's CCotw container blocks outbound port 22 (a blanket egress rule, not
Tangled-specific), and Tangled refuses HTTPS push. That sounds like a dead end
for `git push` to Tangled, but Tangled's `sh.tangled.repo.create` lexicon
accepts an optional `source` URL — the knot does the `git clone --bare`
server-side over HTTPS on our behalf:

```bash
# from CCotw, after `tg auth login`:
tg repo create my-mirror \
    --source https://github.com/me/my-repo.git \
    --description "Server-side mirror"
```

The knot fetches the URL itself, populates the bare repo, and assigns a fresh
repoDid. All operations stay over port 443.

**Caveat (upstream bug — [tangled.org/core issue ⟨tbd⟩](#)):** if you delete a
Tangled repo and recreate one with the same name, the new bare repo gets
orphaned behind a stale alias row — `repo.delete` cleans up `repo_keys` but not
`repo_aliases`, and `INSERT...ON CONFLICT DO NOTHING` then prevents the alias
from updating. Workaround: re-create with a different name (the reason this
mirror is named `claude-tangled-spoke-mirror` rather than the bare repo name).

### Updating the mirror

Since the knot only clones once on create, mirror updates need a second pass.
Either:

- One-off `git push` from a machine with SSH egress (your laptop):
  ```bash
  git remote add tangled [email protected]:austegard.com/claude-tangled-spoke-mirror
  git push tangled main
  ```
- A GitHub Actions workflow on `oaustegard/claude-tangled-spoke` that mirrors to
  Tangled on each push to `main` (e.g. the [Push to tangled.org](https://github.com/marketplace/actions/push-to-tangled-org) marketplace action with an SSH key as a repo secret).

## Acknowledgments

- [`onevcat/tang`](https://github.com/onevcat/tang) — Go CLI for Tangled with
  full coverage. `tg` here is a smaller stdlib-only Python rewrite focused on
  headless containers, but the lexicon shapes, default endpoints, patch-based
  PR model, and protocol semantics were all learned by reading tang's source
  and excellent [`ai-docs/INIT_PLAN.md`](https://github.com/onevcat/tang/tree/main/ai-docs).
- The Tangled team for [docs.tangled.org](https://docs.tangled.org) and
  [blog.tangled.org](https://blog.tangled.org).

## License

MIT
