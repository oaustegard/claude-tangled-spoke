---
name: tg
description: |
  Use this skill when the user asks about Tangled (https://tangled.org) —
  the federated git host built on ATProto — or any of its repos
  (`tangled.org/<owner>/<name>`, e.g. `onev.cat/tang`). Triggers include:
  "list issues on …", "open a Tangled PR", "comment on Tangled issue X",
  "show pulls on …", "view this Tangled repo", "register an SSH key with
  Tangled", or anything mentioning an `at://…/sh.tangled.*` URI.

  This skill wraps the `tg` CLI (a stdlib-only Python client for Tangled)
  with a one-shot auth bootstrap. Credentials come from environment:
  `ATPROTO_HANDLE` / `ATPROTO_APP_PASSWORD` first, then `BSKY_HANDLE` /
  `BSKY_APP_PASSWORD` as a fallback (CCotw and most Claude environments
  expose the BSKY_* names). App passwords are obtained from
  https://bsky.app/settings/app-passwords — never use the main account
  password.
---

# tg — Tangled CLI skill

## Before any `tg` command, run the bootstrap

```bash
bash skills/tg/auth.sh
```

The script self-locates the vendored `bin/tg` relative to its own path,
so it doesn't matter what the current working directory is — but the
path above assumes the project root is `cwd`, which is the usual claude
agent default. If you're elsewhere, use the absolute path.

`auth.sh`:
1. Symlinks the vendored `bin/tg` onto `$PATH` if not already there.
2. Maps `BSKY_HANDLE`/`BSKY_APP_PASSWORD` to the `ATPROTO_*` names that
   `tg auth login` reads.
3. Runs `tg auth login` only if there's no live session.

After the bootstrap, `tg auth status` should show a handle/DID/PDS. If it
doesn't, stop and surface the error — do not retry blindly.

## What `tg` can do

```bash
# Reads — work anonymously, no auth needed
tg repo list <handle>
tg repo view <owner>/<name>
tg issue list  --repo <owner>/<name>
tg issue view  --repo <owner>/<name> <rkey>
tg pr   list   --repo <owner>/<name>
tg pr   view   --repo <owner>/<name> <rkey>
tg pr   patch  --repo <owner>/<name> <rkey>    # prints the latest round's diff

# Writes — require an authenticated session
tg issue create  --repo <owner>/<name> --title "…" --body "…"
tg issue comment --repo <owner>/<name> <rkey> --body "…"
tg issue close   --repo <owner>/<name> <rkey>
tg pr    comment --repo <owner>/<name> <rkey> --body "…"
tg pr    create  --repo <owner>/<name> --from <branch> --base main --title "…"
tg ssh-key add ~/.ssh/id_ed25519.pub --name <label>
```

## Identifiers — use rkeys, not numbers

`tg` lists issues and PRs by **rkey** (the 13-char trailing segment of an
at-uri, e.g. `3mkux6xc5n22k`). The sequential `#N` numbers shown in the
Tangled web UI are AppView-assigned and not visible via the records
themselves — never construct them. If the user pastes a web URL like
`tangled.org/<owner>/<name>/issues/3`, ask which rkey they mean, or run
`tg issue list` first and match by title.

## What `tg` does NOT do (use the web UI)

- `pr merge / close / reopen` (Knot service-auth not yet wired)
- `pr checkout` (a normal `git fetch` works for branch-based PRs only)
- `repo create` is supported with `--source <https-url>` (the Knot clones
  server-side); SSH-push repo creation is not.

## Cloning Tangled repos

Always clone into `./.spokes/<name>` in the user's workspace — the
directory is gitignored by the hub config so spokes don't pollute git
state:

```bash
tg repo clone <owner>/<name> .spokes/<name>
```

Read-only HTTPS clones work from any environment. `git push` to Tangled
needs SSH egress on port 22, which most Claude environments block —
prefer `tg pr create` (patch-based, HTTPS-only) for contributions.

## When to stop and ask

- The user pastes a Tangled web URL with a numeric ID — confirm the
  target before guessing the rkey.
- A write operation would touch a repo the user doesn't own and you have
  no clear instruction to act there.
- `tg auth status` reports unauthenticated and no `*_APP_PASSWORD` is
  set — ask how they want to supply credentials.

## Federation tax: self-hosted PDSes

ATProto lets accounts host their own Personal Data Server (PDS) outside
the central `bsky.network` infrastructure. `tg` resolves every read
through the owner's PDS, so when that PDS isn't reachable from the
current environment (e.g. a proxy with a host allowlist), reads fail.

Concretely in proxied environments like claude.ai:

- Repos owned by accounts on `*.bsky.network` or `*.tangled.sh` PDSes
  work normally.
- Repos owned by accounts with **self-hosted** PDSes (e.g. `mitchellh.com`
  → `pds.mitchellh.com`) are not reachable. `tg` surfaces a clear error
  naming the PDS host and pointing at the web UI fallback.
- Self-hosted **contributors** (issue authors, commenters) on an
  otherwise-reachable repo are gracefully skipped — listings still
  succeed without that author's records.

If you hit a self-hosted-PDS owner, the fallbacks are: read via the web
UI at `https://tangled.org/<owner>/<repo>`, or run `tg` from an
environment with open HTTP egress (e.g. a Claude Code on the Web
container).
