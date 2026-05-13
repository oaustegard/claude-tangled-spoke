# Claude Tangled Spoke

This repo is the **hub** — it configures your Claude Code on the Web session
with authenticated access to [Tangled](https://tangled.org), the federated
git host built on ATProto.

A drop-in analog of [`claude-github-and-spoke`](https://github.com/oaustegard/claude-github-and-spoke)
for the ATProto developer base.

## What this gives you

After session start, your CCotw session has:

- **`git` over SSH** to Tangled — `git clone`, `push`, `pull` against any
  `tangled.org` repo your SSH key can reach
- **`tg` CLI** — authenticated against your PDS via an ATProto app password,
  with subcommands for `auth`, `repo`, `issue`, `pr`, and `ssh-key`
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
3. (Optional) Drop an SSH private key at `.ssh/id_ed25519` *inside the hub repo*
   (also gitignored) — needed for git push to Tangled. Register the matching
   public key via `tg ssh-key add ~/.ssh/id_ed25519.pub` once logged in.
4. Open the repo in Claude Code on the Web.
5. The `SessionStart` hook runs `boot.sh` automatically.

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

The source of truth for this repo is on Tangled at
`tangled.org/austegard.com/claude-tangled-spoke` (or wherever
@oaustegard ends up — `tg repo list oaustegard.bsky.social` will tell you).
GitHub holds a mirror so CCotw can clone it on first launch via HTTPS without
needing SSH credentials pre-provisioned.

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
