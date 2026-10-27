#!/usr/bin/env python3
"""Tests for download retries (`_download` in bin/neutron).

A fresh-HOME release test of runtime 119 (2026-10-13) failed `neutron setup` on one HTTP 500 from GitHub for a
font file; the second run passed. `_download` now retries a transient failure (5xx, 429, a timed-out, reset or
cut-short connection) after each of DOWNLOAD_RETRY_DELAYS, never a 404, and setup's failure summary ends with a
"run it again" line. Each test serves scripted responses from a local HTTP server.

Run:  python3 tests/test_download_retry.py
"""
import http.server
import importlib.machinery
import importlib.util
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error

_CLI = os.environ.get("NEUTRON_CLI_UNDER_TEST") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()
BODY = b"neutron" * 1000


class Script:
    """Responses served in order, one per request; the last one repeats."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = 0

    def next(self):
        self.requests += 1
        return self.steps[min(self.requests, len(self.steps)) - 1]


def _serve(script):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            step = script.next()
            if step == "ok":
                self.send_response(200)
                self.send_header("Content-Length", str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY)
            elif step == "short":                        # promise the whole body, send half, hang up
                self.send_response(200)
                self.send_header("Content-Length", str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY[:len(BODY) // 2])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
            elif step == "slow":                         # longer than the test's DOWNLOAD_TIMEOUT
                time.sleep(1.0)
                self.send_response(200)
                self.send_header("Content-Length", str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY)
            else:                                        # an HTTP status code
                self.send_response(int(step))
                self.send_header("Content-Length", "0")
                self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class DownloadRetry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="neutron-dl-")
        self.dest = os.path.join(self.dir, "file")
        # getattr: NEUTRON_CLI_UNDER_TEST may name a CLI from before retries (the known-bad run)
        self.saved = (getattr(N, "DOWNLOAD_RETRY_DELAYS", None), getattr(N, "DOWNLOAD_TIMEOUT", None))
        N.DOWNLOAD_RETRY_DELAYS = (0, 0, 0)
        N.DOWNLOAD_TIMEOUT = 0.3
        self.srv = None

    def tearDown(self):
        N.DOWNLOAD_RETRY_DELAYS, N.DOWNLOAD_TIMEOUT = self.saved
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
        shutil.rmtree(self.dir)

    def get(self, script):
        self.srv = _serve(script)
        return N._download("http://127.0.0.1:%d/f" % self.srv.server_address[1], self.dest, True)

    def assertGotBody(self):
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BODY)

    def test_a_500_then_200_succeeds_on_the_second_attempt(self):
        s = Script("500", "ok")
        self.assertEqual(self.get(s), len(BODY))
        self.assertEqual(s.requests, 2)
        self.assertGotBody()

    def test_429_is_retried(self):
        s = Script("429", "ok")
        self.get(s)
        self.assertEqual(s.requests, 2)

    def test_a_404_is_not_retried(self):
        s = Script("404", "ok")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(s)
        self.assertEqual(cm.exception.code, 404)
        self.assertEqual(s.requests, 1)

    def test_a_persistent_500_gives_up_after_every_attempt(self):
        s = Script("500")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(s)
        self.assertEqual(cm.exception.code, 500)
        self.assertEqual(s.requests, len(N.DOWNLOAD_RETRY_DELAYS) + 1)

    def test_a_body_cut_short_is_retried_and_rewritten(self):
        s = Script("short", "ok")
        self.get(s)
        self.assertEqual(s.requests, 2)
        self.assertGotBody()

    def test_a_body_cut_short_every_time_raises_an_oserror(self):
        # callers catch OSError/URLError; a short body must never escape as anything else
        s = Script("short")
        with self.assertRaises(OSError):
            self.get(s)
        self.assertEqual(s.requests, len(N.DOWNLOAD_RETRY_DELAYS) + 1)

    def test_a_timeout_is_retried(self):
        s = Script("slow", "ok")
        self.get(s)
        self.assertEqual(s.requests, 2)
        self.assertGotBody()

    def test_a_local_path_is_copied(self):
        src = os.path.join(self.dir, "src")
        with open(src, "wb") as f:
            f.write(BODY)
        self.assertEqual(N._download(src, self.dest, True), len(BODY))
        self.assertGotBody()


class NameLookup(unittest.TestCase):
    """2026-10-27, Fedora 44 VM: one "[Errno -5] No address associated with hostname" lost Mud Hut and
    Collider from setup; the next 40 lookups all answered. A failed lookup is retried, in downloads and
    in the GitHub release lookup."""

    def setUp(self):
        self.saved = getattr(N, "DOWNLOAD_RETRY_DELAYS", None)
        N.DOWNLOAD_RETRY_DELAYS = (0, 0, 0)

    def tearDown(self):
        N.DOWNLOAD_RETRY_DELAYS = self.saved

    @staticmethod
    def lookup_error():
        return urllib.error.URLError(socket.gaierror(-5, "No address associated with hostname"))

    def test_a_failed_lookup_is_retryable(self):
        self.assertTrue(N._download_retryable(self.lookup_error()))

    def test_release_lookup_retries_then_succeeds(self):
        import io
        import urllib.request
        from unittest import mock
        ok = io.BytesIO(b'{"tag_name": "v0.1.14", "assets": []}')
        with mock.patch.object(urllib.request, "urlopen", side_effect=[self.lookup_error(), ok]) as m:
            self.assertEqual(N._gh_latest("Collider")["version"], "0.1.14")
        self.assertEqual(m.call_count, 2)

    def test_release_lookup_failure_reads_as_words(self):
        import urllib.request
        from unittest import mock
        with mock.patch.object(urllib.request, "urlopen", side_effect=self.lookup_error()):
            with self.assertRaises(RuntimeError) as cm:
                N._gh_latest("Collider")
        self.assertIn("could not look up api.github.com", str(cm.exception))
        self.assertNotIn("Errno", str(cm.exception))


class RerunHint(unittest.TestCase):
    def test_names_the_command_that_failed(self):
        self.assertIn("`neutron setup` again", N.setup_rerun_hint(False))
        self.assertIn("`neutron update` again", N.setup_rerun_hint(True))


if __name__ == "__main__":
    unittest.main()
