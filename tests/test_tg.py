"""Tests for tg.

Run: python3 -m pytest tests/ -q     (or)     python3 tests/test_tg.py

No third-party deps required when run as `python3 tests/test_tg.py` — falls
back to unittest if pytest isn't installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import importlib.machinery
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _load_tg():
    # tg has no .py extension, so we must pass an explicit SourceFileLoader.
    path = str(ROOT / "bin" / "tg")
    loader = importlib.machinery.SourceFileLoader("tg", path)
    spec = importlib.util.spec_from_loader("tg", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tg"] = mod
    loader.exec_module(mod)
    return mod


tg = _load_tg()


class TidTests(unittest.TestCase):
    def test_length_and_charset(self):
        for _ in range(50):
            tid = tg.new_tid()
            self.assertEqual(len(tid), 13)
            self.assertTrue(all(c in tg._TID_ALPHABET for c in tid), tid)

    def test_monotonic_ish(self):
        # Two TIDs from the same microsecond can differ in randomness, but
        # successive calls should be sortable in time order in aggregate.
        ids = [tg.new_tid() for _ in range(20)]
        self.assertEqual(len(set(ids)), 20)  # all unique


class AtUriTests(unittest.TestCase):
    def test_parse_ok(self):
        self.assertEqual(
            tg.parse_at_uri("at://did:plc:abc/sh.tangled.repo/3mkunj"),
            ("did:plc:abc", "sh.tangled.repo", "3mkunj"),
        )

    def test_parse_rejects_non_at(self):
        with self.assertRaises(ValueError):
            tg.parse_at_uri("https://example.com/foo/bar")

    def test_parse_rejects_short(self):
        with self.assertRaises(ValueError):
            tg.parse_at_uri("at://did:plc:abc/sh.tangled.repo")


class NormalizeStateTests(unittest.TestCase):
    def test_strips_prefix(self):
        self.assertEqual(
            tg._normalize_state("sh.tangled.repo.issue.state.closed",
                                tg.NSID_ISSUE_STATE),
            "closed",
        )

    def test_passes_through_bare(self):
        self.assertEqual(tg._normalize_state("open", tg.NSID_ISSUE_STATE), "open")

    def test_empty_defaults_to_open(self):
        self.assertEqual(tg._normalize_state("", tg.NSID_PULL_STATUS), "open")


class XrpcPostBodyShapeTests(unittest.TestCase):
    """`com.atproto.server.refreshSession` rejects any request body, so
    `xrpc_post(..., body=None)` must send no payload and no Content-Type."""

    def _capture(self, body):
        seen = {}

        def fake_request(method, url, *, headers=None, data=None, timeout=30.0):
            seen["method"] = method
            seen["headers"] = dict(headers or {})
            seen["data"] = data
            return 200, b'{"ok":true}', {}

        with mock.patch.object(tg, "_request", side_effect=fake_request):
            tg.xrpc_post("https://pds.example", "com.atproto.server.refreshSession",
                         body=body, token="R")
        return seen

    def test_body_none_sends_no_payload_or_content_type(self):
        seen = self._capture(None)
        self.assertIsNone(seen["data"])
        self.assertNotIn("Content-Type", seen["headers"])
        self.assertEqual(seen["headers"].get("Authorization"), "Bearer R")

    def test_body_dict_sends_json_payload(self):
        seen = self._capture({"foo": "bar"})
        self.assertEqual(json.loads(seen["data"]), {"foo": "bar"})
        self.assertEqual(seen["headers"].get("Content-Type"), "application/json")


class CmdAuthRefreshTests(unittest.TestCase):
    """Regression: `tg auth refresh` used to POST `body={}`, which the PDS
    rejects with `InvalidRequest: A request body was provided when none was
    expected`. The fix routes through `body=None`."""

    def test_refresh_posts_no_body_and_rotates_tokens(self):
        sess = tg.Session(did="did:plc:abc", handle="alice.bsky.social",
                          pds="https://pds.example",
                          access_jwt="OLD-A", refresh_jwt="OLD-R")
        calls = []

        def fake_xrpc_post(host, method, *, body, token=None,
                           content_type="application/json"):
            calls.append((host, method, body, token))
            self.assertEqual(method, "com.atproto.server.refreshSession")
            self.assertIsNone(body)
            self.assertEqual(token, "OLD-R")
            return {"accessJwt": "NEW-A", "refreshJwt": "NEW-R"}

        with mock.patch.object(tg.Session, "load", return_value=sess), \
             mock.patch.object(tg.Session, "save", autospec=True) as save, \
             mock.patch.object(tg, "xrpc_post", side_effect=fake_xrpc_post):
            rc = tg.cmd_auth_refresh(argparse.Namespace())
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sess.access_jwt, "NEW-A")
        self.assertEqual(sess.refresh_jwt, "NEW-R")
        save.assert_called_once()


class SplitRepoTests(unittest.TestCase):
    def test_owner_and_name(self):
        self.assertEqual(
            tg._split_repo_arg("alice.tngl.sh/myrepo", lambda: "fallback"),
            ("alice.tngl.sh", "myrepo"),
        )

    def test_name_only_uses_default(self):
        self.assertEqual(
            tg._split_repo_arg("myrepo", lambda: "fallback.handle"),
            ("fallback.handle", "myrepo"),
        )

    def test_strips_at_prefix(self):
        self.assertEqual(
            tg._split_repo_arg("@alice/myrepo", lambda: "x"),
            ("alice", "myrepo"),
        )


class CloneHostTests(unittest.TestCase):
    def test_default_knot_uses_tangled_org(self):
        self.assertEqual(tg._clone_host("knot1.tangled.sh"), "tangled.org")

    def test_custom_knot_passthrough(self):
        self.assertEqual(tg._clone_host("knot.example.com"), "knot.example.com")


class RepoRecordToDictTests(unittest.TestCase):
    def test_builds_clone_urls(self):
        out = tg._repo_record_to_dict(
            owner="alice.tngl.sh",
            owner_did="did:plc:abc",
            record_uri="at://did:plc:abc/sh.tangled.repo/r1",
            value={"name": "demo", "knot": "knot1.tangled.sh",
                   "description": "hi", "createdAt": "2026-01-01T00:00:00Z"},
        )
        self.assertEqual(out["owner"], "alice.tngl.sh")
        self.assertEqual(out["name"], "demo")
        self.assertEqual(out["clone_ssh"], "git@tangled.org:alice.tngl.sh/demo")
        self.assertEqual(out["clone_https"], "https://tangled.org/alice.tngl.sh/demo")
        self.assertEqual(out["description"], "hi")

    def test_custom_knot_keeps_host(self):
        out = tg._repo_record_to_dict(
            owner="alice", owner_did="did:plc:abc",
            record_uri="at://did:plc:abc/sh.tangled.repo/r1",
            value={"name": "demo", "knot": "knot.example.com"},
        )
        self.assertEqual(out["clone_ssh"], "git@knot.example.com:alice/demo")

    def test_carries_repo_did(self):
        # AppView routes issue/PR records by repoDid (the Knot's DID, distinct
        # from the owner DID). We have to surface it from the repo record so
        # downstream writers can include it.
        out = tg._repo_record_to_dict(
            owner="alice", owner_did="did:plc:owner",
            record_uri="at://did:plc:owner/sh.tangled.repo/r1",
            value={"name": "demo", "knot": "knot1.tangled.sh",
                   "repoDid": "did:plc:knothost"},
        )
        self.assertEqual(out["repo_did"], "did:plc:knothost")

    def test_repo_did_defaults_to_empty(self):
        out = tg._repo_record_to_dict(
            owner="alice", owner_did="did:plc:owner",
            record_uri="at://did:plc:owner/sh.tangled.repo/r1",
            value={"name": "demo"},
        )
        self.assertEqual(out["repo_did"], "")


class SessionRoundTripTests(unittest.TestCase):
    def test_save_load_clear(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(tg, "CONFIG_DIR", Path(td)), \
                 mock.patch.object(tg, "SESSION_PATH", Path(td) / "session.json"):
                sess = tg.Session(did="did:plc:abc", handle="alice.bsky.social",
                                  pds="https://pds.example", access_jwt="A",
                                  refresh_jwt="R")
                sess.save()
                loaded = tg.Session.load()
                self.assertEqual(loaded.handle, "alice.bsky.social")
                self.assertEqual(loaded.access_jwt, "A")
                # mode 0o600
                mode = (Path(td) / "session.json").stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)
                tg.Session.clear()
                with self.assertRaises(SystemExit):
                    tg.Session.load()


class ListReposMockedTests(unittest.TestCase):
    def test_list_user_repos_maps_records(self):
        fake_records = [
            {"uri": "at://did:plc:abc/sh.tangled.repo/r1",
             "value": {"name": "first", "knot": "knot1.tangled.sh",
                       "description": "one", "createdAt": "2026-01-01T00:00:00Z"}},
            {"uri": "at://did:plc:abc/sh.tangled.repo/r2",
             "value": {"name": "second", "knot": "knot1.tangled.sh",
                       "createdAt": "2026-01-02T00:00:00Z"}},
        ]
        with mock.patch.object(tg, "_resolve_owner",
                               return_value=("did:plc:abc", "https://pds.example")), \
             mock.patch.object(tg, "list_records", return_value=fake_records):
            repos = tg.list_user_repos("alice.tngl.sh")
        self.assertEqual([r["name"] for r in repos], ["first", "second"])
        self.assertEqual(repos[0]["clone_https"],
                         "https://tangled.org/alice.tngl.sh/first")


class ListRepoIssuesMockedTests(unittest.TestCase):
    def _fake_repo(self):
        return {
            "uri": "at://did:plc:a/sh.tangled.repo/repo1",
            "repo_did": "did:plc:knothost",
            "owner": "alice", "owner_did": "did:plc:a", "name": "demo",
        }

    def test_filters_and_dedupes_across_targets(self):
        # New records' .repo points at the Knot DID; legacy records point at
        # the repo at-uri. list_repo_issues must query both and dedupe so old
        # and new issues surface together without duplicates.
        targets_queried = []

        def fake_constellation(target, collection, path, **kw):
            if collection == tg.NSID_ISSUE:
                targets_queried.append(target)
                if target == "did:plc:knothost":
                    # New-format record only
                    return [{"did": "did:plc:a", "collection": collection, "rkey": "x1"}]
                if target.startswith("at://"):
                    # Both records appear under the at-uri target (x1 from
                    # legacy migration, x2 is a pure-legacy record).
                    return [
                        {"did": "did:plc:a", "collection": collection, "rkey": "x1"},
                        {"did": "did:plc:a", "collection": collection, "rkey": "x2"},
                    ]
            if collection == tg.NSID_ISSUE_STATE:
                if target.endswith("/x1"):
                    return [{"did": "did:plc:a",
                             "collection": tg.NSID_ISSUE_STATE, "rkey": "s1"}]
                return []
            return []

        def fake_get_record(pds, did, collection, rkey):
            if collection == tg.NSID_ISSUE:
                title = "First" if rkey == "x1" else "Second"
                created = "2026-01-01" if rkey == "x1" else "2026-01-02"
                return {"uri": f"at://{did}/{collection}/{rkey}",
                        "value": {"title": title, "body": "b",
                                  "createdAt": f"{created}T00:00:00Z"}}
            if collection == tg.NSID_ISSUE_STATE:
                return {"value": {"state": "sh.tangled.repo.issue.state.closed"}}
            raise AssertionError(collection)

        with mock.patch.object(tg, "constellation_links",
                               side_effect=fake_constellation), \
             mock.patch.object(tg, "resolve_did_pds",
                               return_value="https://pds.example"), \
             mock.patch.object(tg, "get_record", side_effect=fake_get_record):
            issues = tg.list_repo_issues(self._fake_repo())

        # Both targets were queried.
        issue_targets = [t for t in targets_queried]
        self.assertIn("did:plc:knothost", issue_targets)
        self.assertIn("at://did:plc:a/sh.tangled.repo/repo1", issue_targets)
        # x1 returned from both queries but appears once.
        self.assertEqual([i["title"] for i in issues], ["First", "Second"])
        self.assertEqual([i["state"] for i in issues], ["closed", "open"])
        for i in issues:
            self.assertNotIn("number", i)
            self.assertTrue(i["uri"].startswith("at://"))


class RepoCreateMockedTests(unittest.TestCase):
    def _run_create(self, source=None):
        sess = tg.Session(did="did:plc:abc", handle="alice.bsky.social",
                          pds="https://pds.example", access_jwt="A", refresh_jwt="R")
        calls = []
        knot_body = {}

        def fake_xrpc_get(host, method, params=None, token=None):
            calls.append(("GET", method))
            if method == "com.atproto.server.getServiceAuth":
                self.assertEqual(params["aud"], "did:web:knot1.tangled.sh")
                self.assertEqual(params["lxm"], "sh.tangled.repo.create")
                return {"token": "SVC"}
            raise AssertionError(method)

        def fake_xrpc_post(host, method, body, token=None, content_type="application/json"):
            calls.append(("POST", method))
            if method == "sh.tangled.repo.create":
                self.assertEqual(token, "SVC")
                knot_body.update(body)
                return {"repoDid": "did:web:demo.knot"}
            if method == "com.atproto.repo.putRecord":
                self.assertEqual(token, "A")
                return {"uri": f"at://{sess.did}/{tg.NSID_REPO}/{body['rkey']}",
                        "cid": "bafy"}
            raise AssertionError(method)

        argv = argparse.Namespace(name="demo", description="", default_branch="main",
                                  knot=None, source=source)
        with mock.patch.object(tg.Session, "load", return_value=sess), \
             mock.patch.object(tg, "xrpc_get", side_effect=fake_xrpc_get), \
             mock.patch.object(tg, "xrpc_post", side_effect=fake_xrpc_post):
            rc = tg.cmd_repo_create(argv)
        return rc, calls, knot_body

    def test_create_without_source(self):
        rc, calls, body = self._run_create(source=None)
        self.assertEqual(rc, 0)
        self.assertEqual([c[1] for c in calls],
            ["com.atproto.server.getServiceAuth",
             "sh.tangled.repo.create",
             "com.atproto.repo.putRecord"])
        self.assertNotIn("source", body)
        self.assertEqual(body["defaultBranch"], "main")

    def test_create_with_source_forwards_to_knot(self):
        url = "https://github.com/u/r.git"
        rc, calls, body = self._run_create(source=url)
        self.assertEqual(rc, 0)
        # Same call sequence; knot body now carries `source` so the knot can
        # `git clone --bare <url>` server-side over HTTPS.
        self.assertEqual(body["source"], url)
        self.assertEqual(body["name"], "demo")


class IssueCreateMockedTests(unittest.TestCase):
    def _fake_repo(self, repo_did="did:plc:knothost"):
        return {
            "owner": "alice", "owner_did": "did:plc:owner", "name": "demo",
            "uri": "at://did:plc:owner/sh.tangled.repo/r1",
            "repo_did": repo_did, "knot": "knot1.tangled.sh",
        }

    def _run_create(self, repo, body=None):
        sess = tg.Session(did="did:plc:owner", handle="alice", pds="https://pds",
                          access_jwt="A", refresh_jwt="R")
        written = {}

        def fake_create_record(s, collection, record, rkey=None):
            written["collection"] = collection
            written["record"] = record
            return {"uri": f"at://{s.did}/{collection}/xxxx", "cid": "bafy"}

        argv = argparse.Namespace(repo="alice/demo", title="hi", body=body)
        with mock.patch.object(tg.Session, "load", return_value=sess), \
             mock.patch.object(tg, "_resolve_repo", return_value=repo), \
             mock.patch.object(tg, "create_record", side_effect=fake_create_record), \
             mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = tg.cmd_issue_create(argv)
        return rc, written

    def test_repo_field_is_knot_did(self):
        # Per the canonical lexicon, `sh.tangled.repo.issue.repo` is
        # `format: "did"` — the Knot's DID, NOT the repo at-uri. AppView's
        # ingester rejects at-uri values via syntax.ParseDID.
        rc, written = self._run_create(self._fake_repo())
        self.assertEqual(rc, 0)
        self.assertEqual(written["record"]["repo"], "did:plc:knothost")
        self.assertEqual(written["record"]["title"], "hi")

    def test_no_repodid_companion_field(self):
        # The old companion `repoDid` field is never read by AppView's
        # ingester (IssueFromRecord pulls RepoDid from record.Repo). Don't
        # waste bytes on it.
        rc, written = self._run_create(self._fake_repo())
        self.assertEqual(rc, 0)
        self.assertNotIn("repoDid", written["record"])

    def test_exits_when_repo_has_no_did(self):
        # Without a Knot DID we can't write a valid record — fail loudly
        # rather than ship a record AppView will silently drop.
        with self.assertRaises(SystemExit):
            self._run_create(self._fake_repo(repo_did=""))


class IdentifierHelperTests(unittest.TestCase):
    def test_rkey_from_uri(self):
        self.assertEqual(
            tg._rkey_from_uri("at://did:plc:abc/sh.tangled.repo.issue/3mlp5qwdg4g25"),
            "3mlp5qwdg4g25",
        )

    def test_rkey_from_repo_uri(self):
        self.assertEqual(
            tg._rkey_from_uri("at://did:plc:abc/sh.tangled.repo/3mkunj73ac422"),
            "3mkunj73ac422",
        )


class ParserSmokeTests(unittest.TestCase):
    """The CLI surface must parse without exceptions."""

    def test_all_subcommand_help(self):
        import io, contextlib
        parser = tg.build_parser()
        sink = io.StringIO()
        for argv in [
            ["auth", "login", "--help"],
            ["auth", "status", "--help"],
            ["repo", "list", "--help"],
            ["repo", "view", "--help"],
            ["repo", "clone", "--help"],
            ["repo", "create", "--help"],
            ["issue", "list", "--help"],
            ["issue", "view", "--help"],
            ["issue", "create", "--help"],
            ["issue", "comment", "--help"],
            ["issue", "close", "--help"],
            ["pr", "list", "--help"],
            ["pr", "view", "--help"],
            ["pr", "comment", "--help"],
            ["pr", "patch", "--help"],
            ["pr", "create", "--help"],
            ["ssh-key", "list", "--help"],
            ["ssh-key", "add", "--help"],
            ["ssh-key", "delete", "--help"],
        ]:
            with self.subTest(argv=argv), \
                 contextlib.redirect_stdout(sink), \
                 contextlib.redirect_stderr(sink), \
                 self.assertRaises(SystemExit) as cm:
                parser.parse_args(argv)
            self.assertEqual(cm.exception.code, 0, f"{argv} → {cm.exception.code}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
