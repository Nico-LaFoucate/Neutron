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


class Premiere2026DirectXDisplay(unittest.TestCase):
    """Neutron#21 (2026-10-14): Premiere 2026+ draws its Transform/Crop handles with a GPU overlay renderer
    that Adobe's OpenGL display drops, so Premiere 2026+ keeps Adobe's default DirectX display (`false`) --
    including undoing the `true` older CLIs wrote -- and launches with blit-to-window off. Premiere 2025
    keeps `true`. Each test starts from the state an older CLI left behind (the known-bad state)."""

    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-dfix26-")
        drive = os.path.join(self.prefix, "drive_c")
        self.adobe = os.path.join(drive, "Program Files", "Adobe")
        self.roaming = os.path.join(drive, "users", USER, "AppData", "Roaming", "Adobe")
        os.makedirs(self.roaming)   # a real user profile; without it no user is found and nothing runs
        self.sys32 = os.path.join(drive, "windows", "system32")
        os.makedirs(self.sys32)
        self._dxgi(fixed=True)      # runtime 11.10-121+ provisioned this prefix
        self._running = N._running_app_ids
        N._running_app_ids = lambda prefix: []
        self._user = os.environ.get("USER")
        os.environ["USER"] = USER

    def tearDown(self):
        N._running_app_ids = self._running
        if self._user is None:
            os.environ.pop("USER", None)
        else:
            os.environ["USER"] = self._user
        shutil.rmtree(self.prefix, ignore_errors=True)

    def _dxgi(self, fixed):
        """The prefix's DXVK dxgi.dll: 11.10-121+ has no BackgroundColor strings; older ones have the stubs'."""
        with open(os.path.join(self.sys32, "dxgi.dll"), "wb") as f:
            f.write(b"MZ...DxgiSwapChain::Present..." if fixed else
                    b"MZ...DxgiSwapChain::GetBackgroundColor: Not implemented...")

    def _premiere(self, year, prefs=None):
        os.makedirs(os.path.join(self.adobe, "Adobe Premiere Pro %d" % year), exist_ok=True)
        with open(os.path.join(self.adobe, "Adobe Premiere Pro %d" % year, "Adobe Premiere Pro.exe"), "w"):
            pass
        if prefs is None:
            return None
        d = os.path.join(self.roaming, "Premiere Pro", "%d.0" % (year - 2000))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "Debug Database.txt")
        with open(path, "w", newline="") as f:
            f.write(prefs)
        return path

    def _run(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            N._display_fix_before_launch(self.prefix)
        return out.getvalue(), err.getvalue()

    def _read(self, path):
        with open(path, newline="") as f:
            return f.read()

    def test_2026_reverts_old_fix_and_2025_keeps_it(self):
        old_cli = PREMIERE_PREFS.replace("DisableDirectXDisplay\tfalse", "DisableDirectXDisplay\ttrue")
        p25 = self._premiere(2025, PREMIERE_PREFS)    # fix off: must become true
        p26 = self._premiere(2026, old_cli)           # an older CLI forced true: must go back to false
        out, err = self._run()
        self.assertEqual(out, "")
        self.assertEqual(_settings(self._read(p25))[1], ["DS.DisableDirectXDisplay", "true", "false"])
        self.assertEqual(_settings(self._read(p26)), [
            ["BE.Prefs.Version", "1", "1"],
            ["DS.DisableDirectXDisplay", "false", "false"],
            ["MZ.Some.Other.Key", "42", "0"]])
        before = (self._read(p25), self._read(p26))
        self.assertEqual(self._run(), ("", ""))       # idempotent
        self.assertEqual((self._read(p25), self._read(p26)), before)

    def test_2026_without_the_key_is_left_alone(self):
        prefs = "BE.Prefs.Version\t1\t1\r\r\n"
        p26 = self._premiere(2026, prefs)
        self.assertEqual(self._run(), ("", ""))
        self.assertEqual(self._read(p26), prefs)      # absent key = Adobe's default = what we want

    def test_never_run_2026_gets_no_file(self):
        self._premiere(2026)
        self.assertEqual(self._run(), ("", ""))
        self.assertFalse(os.path.exists(os.path.join(self.roaming, "Premiere Pro")))

    def test_status_reports_2026_default_as_applied(self):
        p26 = self._premiere(2026, PREMIERE_PREFS)
        self.assertTrue(N._display_fix_matches(self._read(p26), N._display_fix_wanted("premiere", p26, self.prefix)))
        p25 = os.path.join(self.roaming, "Premiere Pro", "25.0", "Debug Database.txt")
        self.assertFalse(N._display_fix_matches(PREMIERE_PREFS, N._display_fix_wanted("premiere", p25, self.prefix)))

    def test_display_fix_needed_only_where_there_is_one(self):
        """Collider's "Display fix pending" pill on every Premiere 2026 card: 2026 runs on Adobe's default display, so
        there is no fix, run or never run. 2025, and 2026 on a pinned pre-121 runtime, still need it."""
        self._premiere(2026)                          # never run: no Debug Database
        self.assertFalse(N._premiere_display_fix_needed(self.prefix, USER))
        p26 = self._premiere(2026, PREMIERE_PREFS)    # has run
        self.assertFalse(N._premiere_display_fix_needed(self.prefix, USER, p26))
        self._dxgi(fixed=False)                       # pre-121 dxgi: 2026 stays on the OpenGL display + the fix
        self.assertTrue(N._premiere_display_fix_needed(self.prefix, USER, p26))
        self._dxgi(fixed=True)
        shutil.rmtree(os.path.join(self.roaming, "Premiere Pro"))
        shutil.rmtree(os.path.join(self.adobe, "Adobe Premiere Pro 2026"))
        self._premiere(2025)
        self.assertTrue(N._premiere_display_fix_needed(self.prefix, USER))

    def test_launch_env_blit_to_window_off_for_2026_only(self):
        prof = N.APP_PROFILES["premiere"]
        for year, want in ((2025, None), (2026, "1")):
            exe = os.path.join(self.adobe, "Adobe Premiere Pro %d" % year, "Adobe Premiere Pro.exe")
            env = {}
            N._apply_app_env(env, "premiere", prof, self.prefix, os.path.join(os.path.dirname(exe), "dxvk.conf"),
                             exe=exe)
            self.assertEqual(env.get("NEUTRON_DISABLE_BTW"), want, year)
        self._premiere(2026)
        env = {"NEUTRON_DISABLE_BTW": "0"}           # a caller's A/B still wins
        N._apply_app_env(env, "premiere", prof, self.prefix, "x", protected={"NEUTRON_DISABLE_BTW"},
                         exe=os.path.join(self.adobe, "Adobe Premiere Pro 2026", "Adobe Premiere Pro.exe"))
        self.assertEqual(env["NEUTRON_DISABLE_BTW"], "0")

    def test_older_runtime_keeps_2026_on_the_opengl_display(self):
        """A launcher pinned to a runtime before 11.10-121: its dxgi still fails SetBackgroundColor, so the
        DirectX display would be black. Premiere 2026 must stay exactly as before: true + blit-to-window on."""
        self._dxgi(fixed=False)
        p26 = self._premiere(2026, PREMIERE_PREFS)
        self._run()
        self.assertEqual(_settings(self._read(p26))[1], ["DS.DisableDirectXDisplay", "true", "false"])
        exe = os.path.join(self.adobe, "Adobe Premiere Pro 2026", "Adobe Premiere Pro.exe")
        env = {}
        N._apply_app_env(env, "premiere", N.APP_PROFILES["premiere"], self.prefix,
                         os.path.join(os.path.dirname(exe), "dxvk.conf"), exe=exe)
        self.assertNotIn("NEUTRON_DISABLE_BTW", env)


if __name__ == "__main__":
    unittest.main()
