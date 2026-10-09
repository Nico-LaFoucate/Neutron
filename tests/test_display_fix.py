#!/usr/bin/env python3
"""Tests for the display fix on the way into `neutron launch` (bin/neutron: _display_fix_before_launch).

Until 2026-10-09 only Collider applied DS.DisableDirectXDisplay before a launch, so anyone who
launched from the app menu, the dock, a file association or a terminal never got it. `launch` now
applies it the same way: best-effort, never on a running app, never blocking the launch, and never
writing to stdout (which carries `launch --json` for Collider).

Each test starts from a prefix where the fix is NOT applied (the known-bad state) and checks the
files afterwards. The prefixes are synthetic; nothing here starts wine.

Run:  python3 tests/test_display_fix.py
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()

USER = "tester"
# Adobe's own line endings are CR CR LF.
PREMIERE_PREFS = ("BE.Prefs.Version\t1\t1\r\r\n"
                  "DS.DisableDirectXDisplay\tfalse\tfalse\r\r\n"
                  "MZ.Some.Other.Key\t42\t0\r\r\n")
FIX_LINE = "DS.DisableDirectXDisplay\ttrue\tfalse\r\n"


def _settings(text):
    """The key/current/default rows of a Debug Database, ignoring line endings and blank lines."""
    return [ln.split("\t") for ln in text.replace("\r", "\n").split("\n") if ln.strip()]


class DisplayFixBeforeLaunch(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-dfix-")
        drive = os.path.join(self.prefix, "drive_c")
        adobe = os.path.join(drive, "Program Files", "Adobe")
        roaming = os.path.join(drive, "users", USER, "AppData", "Roaming", "Adobe")
        # Premiere: installed and run before, its prefs carry the fix switched OFF.
        os.makedirs(os.path.join(adobe, "Adobe Premiere Pro 2025"))
        os.makedirs(os.path.join(roaming, "Premiere Pro", "25.0"))
        self.prem = os.path.join(roaming, "Premiere Pro", "25.0", "Debug Database.txt")
        with open(self.prem, "w", newline="") as f:
            f.write(PREMIERE_PREFS)
        # After Effects: installed, never run, so it has no prefs file yet.
        os.makedirs(os.path.join(adobe, "Adobe After Effects 2025"))
        self.ae = os.path.join(roaming, "After Effects", "25.0", "Debug Database.txt")
        # Media Encoder: not installed.
        self._running = N._running_app_ids
        self._user = os.environ.get("USER")
        os.environ["USER"] = USER

    def tearDown(self):
        N._running_app_ids = self._running
        if self._user is None:
            os.environ.pop("USER", None)
        else:
            os.environ["USER"] = self._user
        shutil.rmtree(self.prefix, ignore_errors=True)

    def _run(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            N._display_fix_before_launch(self.prefix)
        return out.getvalue(), err.getvalue()

    def _read(self, path):
        with open(path, newline="") as f:
            return f.read()

    def test_applies_to_every_installed_dva_app(self):
        N._running_app_ids = lambda prefix: []
        out, err = self._run()
        self.assertEqual(out, "", "nothing may reach stdout: it carries `launch --json`")
        # Every setting survives and the fix is on exactly once. (The existing writer leaves an
        # empty line after the line it rewrites in a CR CR LF file; Adobe rewrites the whole file
        # in its own style on exit, and that writer is long proven, so blank lines are ignored.)
        self.assertEqual(_settings(self._read(self.prem)), [
            ["BE.Prefs.Version", "1", "1"],
            ["DS.DisableDirectXDisplay", "true", "false"],
            ["MZ.Some.Other.Key", "42", "0"]])
        self.assertEqual(self._read(self.ae), FIX_LINE)
        self.assertIn("display fix changed", err)
        self.assertIn("display fix created", err)

    def test_idempotent(self):
        N._running_app_ids = lambda prefix: []
        self._run()
        before = (self._read(self.prem), self._read(self.ae))
        out, err = self._run()
        self.assertEqual((self._read(self.prem), self._read(self.ae)), before)
        self.assertEqual((out, err), ("", ""))

    def test_running_app_is_left_alone(self):
        N._running_app_ids = lambda prefix: ["premiere"]
        self._run()
        self.assertEqual(self._read(self.prem), PREMIERE_PREFS)   # untouched while it runs
        self.assertEqual(self._read(self.ae), FIX_LINE)           # the others still get it

    def test_never_raises(self):
        def boom(prefix):
            raise RuntimeError("simulated failure")
        N._running_app_ids = boom
        out, err = self._run()                                    # must not raise
        self.assertEqual(out, "")
        self.assertIn("display fix skipped", err)
        self.assertEqual(self._read(self.prem), PREMIERE_PREFS)

    def test_launch_calls_it(self):
        src = open(_CLI).read()
        launch = src[src.index("def cmd_launch(args):"):]
        launch = launch[:launch.index("\ndef ")]
        self.assertIn("_display_fix_before_launch(prefix)", launch)
        self.assertLess(launch.index("_display_fix_before_launch(prefix)"),
                        launch.index("subprocess.Popen("), "the fix must run before the app starts")


if __name__ == "__main__":
    unittest.main()
