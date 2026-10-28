#!/usr/bin/env python3
"""Which display driver a session gets (`session_display`, 2026-10-28).

His "Allow x11 on x11 sessions": Linux Mint starts Cinnamon on X11 by default and `neutron launch` refused there
("no Wayland session detected, and Neutron does not fall back to X11"). A session that is X11 by every sign now gets
Wine's X11 driver. The August rule still holds for every uncertain case: a launch surface that only lacks the Wayland
variables on a Wayland desktop must not be taken for X11, because that rewrites the prefix's driver.

Known-bad: NEUTRON_CLI_UNDER_TEST=<beta.32> has no session_display (errors), and its plugin installer refuses on X11.

Run:  python3 tests/test_session_display.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

_CLI = os.environ.get("NEUTRON_CLI_UNDER_TEST") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


class SessionDisplay(unittest.TestCase):
    def setUp(self):
        self.rt = tempfile.mkdtemp(prefix="neutron-rt-")

    def tearDown(self):
        for n in os.listdir(self.rt):
            os.remove(os.path.join(self.rt, n))
        os.rmdir(self.rt)

    def mode(self, **env):
        base = {"XDG_RUNTIME_DIR": self.rt, "PATH": os.environ.get("PATH", "")}
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=True):
            return N.session_display()

    def socket(self, name="wayland-0"):
        open(os.path.join(self.rt, name), "w").close()

    def test_wayland_session(self):
        self.socket()
        self.assertEqual(self.mode(WAYLAND_DISPLAY="wayland-0", XDG_SESSION_TYPE="wayland"), "wayland")

    def test_a_real_x11_session_gets_x11(self):
        self.assertEqual(self.mode(XDG_SESSION_TYPE="x11", DISPLAY=":0"), "x11")

    def test_missing_variables_on_a_wayland_desktop_are_not_x11(self):
        # the August case: the compositor's socket is there, the launch surface just lacks the variables
        self.socket("wayland-1")
        self.assertIsNone(self.mode(XDG_SESSION_TYPE="x11", DISPLAY=":0"))
        self.assertIsNone(self.mode(DISPLAY=":0"))

    def test_x11_needs_the_session_to_say_so(self):
        self.assertIsNone(self.mode(DISPLAY=":0"))                       # no XDG_SESSION_TYPE
        self.assertIsNone(self.mode(XDG_SESSION_TYPE="x11"))             # no DISPLAY
        self.assertIsNone(self.mode(XDG_SESSION_TYPE="tty"))

    def test_x11_needs_a_runtime_dir_to_check(self):
        with mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, clear=True):
            self.assertIsNone(N.session_display())

    def test_the_override_still_forces_x11(self):
        self.assertEqual(self.mode(DISPLAY=":0", NEUTRON_ALLOW_X11="1"), "x11")

    def test_a_lock_file_is_not_a_compositor(self):
        self.socket("wayland-0.lock")
        self.assertEqual(self.mode(XDG_SESSION_TYPE="x11", DISPLAY=":0"), "x11")


class ApplySessionDisplay(unittest.TestCase):
    def run_apply(self, mode, env, outer):
        calls = []
        with mock.patch.dict(os.environ, outer, clear=True), \
             mock.patch.object(N, "reg_set", side_effect=lambda *a: calls.append(a)):
            N.apply_session_display("/w/bin/wine", "/p", mode, env)
        return calls

    def test_x11_sets_the_driver_and_keeps_display(self):
        env = {"WAYLAND_DISPLAY": "stale"}
        calls = self.run_apply("x11", env, {"DISPLAY": ":1"})
        self.assertEqual(calls[0][-1], "x11")
        self.assertEqual(env, {"DISPLAY": ":1"})

    def test_wayland_sets_the_driver_and_drops_display(self):
        env = {"DISPLAY": ":0"}
        calls = self.run_apply("wayland", env, {"WAYLAND_DISPLAY": "wayland-1"})
        self.assertEqual(calls[0][-1], "wayland")
        self.assertEqual(env, {"WAYLAND_DISPLAY": "wayland-1"})


class Installer(unittest.TestCase):
    def test_the_plugin_installer_runs_on_x11(self):
        with mock.patch.object(N, "session_display", return_value="x11"), \
             mock.patch.object(N, "apply_session_display") as apply, \
             mock.patch.object(N.subprocess, "run", return_value=mock.Mock(returncode=0)), \
             mock.patch.object(N, "wineserver_wait"), \
             tempfile.TemporaryDirectory() as d, \
             mock.patch.object(N, "NEUTRON_LOGS_DIR", d):
            r = N._run_installer(mock.Mock(json=True), "/p", os.path.join(d, "setup.exe"), "/w/bin/wine")
        self.assertTrue(r["ok"], r)
        self.assertEqual(apply.call_args[0][2], "x11")

    def test_no_session_still_refuses(self):
        with mock.patch.object(N, "session_display", return_value=None):
            r = N._run_installer(mock.Mock(json=True), "/p", "/x/setup.exe", "/w/bin/wine")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
