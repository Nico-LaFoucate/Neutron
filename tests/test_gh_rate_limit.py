#!/usr/bin/env python3
"""GitHub's rate limit is named, not reported as a bare "GitHub answered 403" (2026-10-25).

Without a sign-in GitHub allows 60 API requests an hour per network address. When they run out it answers 403 (or 429)
with X-RateLimit-Remaining: 0 and X-RateLimit-Reset. `neutron setup`/`update` printed "GitHub answered 403 for
Nico-LaFoucate/Collider", which reads like a broken release. Other 403s keep the plain message.

Run:  python3 tests/test_gh_rate_limit.py
"""
import email.message
import importlib.machinery
import importlib.util
import os
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


def _error(code, remaining=None, reset=None):
    h = email.message.Message()
    if remaining is not None:
        h["X-RateLimit-Remaining"] = remaining
    if reset is not None:
        h["X-RateLimit-Reset"] = str(reset)
    return urllib.error.HTTPError("https://api.github.com/x", code, "Forbidden", h, None)


def _latest_message(err):
    with mock.patch.object(urllib.request, "urlopen", side_effect=err):
        with self_raises() as cm:
            N._gh_latest("Collider")
    return str(cm.exception)


class self_raises:
    def __enter__(self):
        return self

    def __exit__(self, typ, val, tb):
        self.exception = val
        return typ is RuntimeError


class RateLimit(unittest.TestCase):
    def test_rate_limit_is_named_with_the_wait(self):
        msg = _latest_message(_error(403, "0", int(time.time()) + 47 * 60 + 5))
        self.assertIn("limit", msg)
        self.assertIn("in 48 minutes", msg)
        self.assertNotIn("answered 403", msg)

    def test_429_too(self):
        self.assertIn("limit", _latest_message(_error(429, "0", int(time.time()) + 30)))

    def test_other_403_keeps_the_plain_message(self):
        self.assertIn("GitHub answered 403", _latest_message(_error(403, "12", int(time.time()) + 60)))
        self.assertIn("GitHub answered 403", _latest_message(_error(403)))

    def test_404_unchanged(self):
        self.assertIn("no published release", _latest_message(_error(404)))


if __name__ == "__main__":
    unittest.main()
