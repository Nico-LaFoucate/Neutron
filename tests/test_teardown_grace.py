#!/usr/bin/env python3
"""Teardown waits its WM_CLOSE grace period only for processes that were SENT a WM_CLOSE (2026-10-18).

`wine taskkill /im NAME` without /F posts WM_CLOSE to the process's top-level windows; Wine's taskkill returns 128 when a
matched process has none. Lightroom's Crash Processor and dynamiclinkmanager, then AdobeIPCBroker, are windowless, and
every Collider clean exit sat out two full 25 s grace periods for them after Lightroom itself had closed: the card said
"Quitting…" for 51 s (lab), and Neutron#27's reporter relaunched in that window.

The "processes" are `sleep` children carrying WINEPREFIX=<tmp prefix> and a Windows-style argv[0], as in
test_identity.py; `wine` is a two-line script that answers taskkill with a fixed exit code. Nothing starts wine.
Validated against the known-bad: on the pre-fix bin/neutron both windowless tests wait the whole grace and fail.

Run:  python3 tests/test_teardown_grace.py
"""
import argparse
import contextlib
import io
import os
import tempfile
import time
import unittest

from test_identity import N, _fake_premiere_prefix, _spawn

GRACE = 4
DAEMON_ARGV0 = r"C:\Program Files (x86)\Common Files\Adobe\Adobe Desktop Common\IPCBox\AdobeIPCBroker.exe"
HELPER_ARGV0 = r"C:\Program Files\Adobe\Adobe Premiere Pro 2025\dynamiclinkmanager.exe"


def _fake_wine(root, rc):
    path = os.path.join(root, "bin", "wine")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nexit %d\n" % rc)
    os.chmod(path, 0o755)
    return path


def _teardown(test, prefix, wine, app=None):
    """Run `neutron teardown` in-process with a fake wine; return the seconds it took."""
    orig = N.resolve_wine
    N.resolve_wine = lambda: (wine, True)
    test.addCleanup(setattr, N, "resolve_wine", orig)
    args = argparse.Namespace(prefix=prefix, path=None, force=False, grace=GRACE, json=True, app=app)
    t = time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        N.cmd_teardown(args)
    return time.monotonic() - t


class FullTeardownGrace(unittest.TestCase):
    def test_windowless_daemon_is_not_waited_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = os.path.join(tmp, "pfx")
            os.makedirs(os.path.join(prefix, "drive_c"))
            _spawn(self, prefix, DAEMON_ARGV0)
            took = _teardown(self, prefix, _fake_wine(tmp, 128))
            self.assertLess(took, GRACE - 0.5, "taskkill said 128 (no window): nothing was asked to close, so "
                            "nothing may be waited for -- the old code sat out the whole grace here")

    def test_process_sent_wm_close_still_gets_its_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = os.path.join(tmp, "pfx")
            os.makedirs(os.path.join(prefix, "drive_c"))
            _spawn(self, prefix, DAEMON_ARGV0)
            took = _teardown(self, prefix, _fake_wine(tmp, 0))
            self.assertGreaterEqual(took, GRACE, "taskkill said 0 (WM_CLOSE posted): the app must get its full "
                                    "grace to save its preferences")


class AppTeardownGrace(unittest.TestCase):
    def test_windowless_helper_is_not_waited_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = _fake_premiere_prefix(tmp, "premiere2025")
            _spawn(self, prefix, HELPER_ARGV0)
            took = _teardown(self, prefix, _fake_wine(tmp, 128), app="premiere")
            self.assertLess(took, GRACE - 0.5)

    def test_helper_sent_wm_close_still_gets_its_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = _fake_premiere_prefix(tmp, "premiere2025")
            _spawn(self, prefix, HELPER_ARGV0)
            took = _teardown(self, prefix, _fake_wine(tmp, 0), app="premiere")
            self.assertGreaterEqual(took, GRACE)


if __name__ == "__main__":
    unittest.main()
