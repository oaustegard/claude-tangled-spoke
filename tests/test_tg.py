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
    def test_filters_and_numbers(self):
        # Two issues, one closed via a state record.
        backlinks_call_count = {"n": 0}

        def fake_constellation(target, collection, path, **kw):
            backlinks_call_count["n"] += 1
            if collection == tg.NSID_ISSUE:
                return [
                    {"did": "did:plc:a", "collection": collection, "rkey": "x1"},
                    {"did": "did:plc:a", "collection": collection, "rkey": "x2"},
                ]
            if collection == tg.NSID_ISSUE_STATE:
                # The first issue (x1) has a closed state record; the second doesn't.
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
            issues = tg.list_repo_issues("at://did:plc:a/sh.tangled.repo/repo1")

        self.assertEqual([i["title"] for i in issues], ["First", "Second"])
        self.assertEqual([i["state"] for i in issues], ["closed", "open"])
        # No fake sequential `number` field — identity comes from rkey/uri.
        # (Tangled's canonical issue numbers come from AppView, not records.)
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
