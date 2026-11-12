#!/usr/bin/env python3
"""The last app's teardown does not sweep the prefix while a third-party program is still running.

The Mister Horse Product Manager is started by its Animation Composer / Premiere Composer plugins
from inside After Effects or Premiere, and asks the user to quit them before it installs a pack.
Collider then runs `teardown --app`, the app was the last Adobe app, so the engine swept the prefix
(wineserver -k) and killed the Product Manager mid-install. On Windows it keeps running.

Adobe's daemons, Wine's own programs and Microsoft runtimes are still swept as before.

Run:  python3 tests/test_teardown_third_party.py
"""
import argparse
import importlib.machinery
import importlib.util
import os
import unittest

_CLI = os.environ.get("NEUTRON_CLI_UNDER_TEST") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")
_spec = importlib.util.spec_from_loader("neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N)

PROCS = {
    101: ("services.exe", False, "C:/windows/system32/services.exe"),
    102: ("AdobeIPCBroker.", True, "C:/Program Files/Common Files/Adobe/Adobe Desktop Common/IPCBox/AdobeIPCBroker.exe"),
    103: ("msedgewebview2.", True, "C:/Program Files (x86)/Microsoft/EdgeWebView/Application/msedgewebview2.exe"),
    104: ("winedbg", True, "C:/windows/system32/winedbg.exe"),
    105: ("bash", True, "/usr/bin/bash"),
}
MH = (201, ("ProductManager.", True, "C:/Program Files/Mister Horse Product Manager/ProductManager.exe"))


class Fake:
    def __init__(self, procs):
        self.procs = procs
        self.swept = False
        self.emitted = None

    def install(self):
        self.saved = {k: getattr(N, k) for k in
                      ("_prefix_procs", "_proc_win_exe", "_app_procs", "_running_app_ids",
                       "_post_wm_close", "cmd_teardown", "emit", "log")}
        N._prefix_procs = lambda prefix: [(p, c, a) for p, (c, a, _e) in self.procs.items()]
        N._proc_win_exe = lambda pid: self.procs[pid][2]
        N._app_procs = lambda prefix, app_id: []        # the app has already exited
        N._running_app_ids = lambda prefix: []           # and it was the last Adobe app
        N._post_wm_close = lambda wine, env, images: set()
        N.cmd_teardown = lambda args, _emitted=False: setattr(self, "swept", True)
        N.emit = lambda obj, as_json=False: setattr(self, "emitted", obj)
        N.log = lambda *a, **k: None

    def restore(self):
        for k, v in self.saved.items():
            setattr(N, k, v)


def teardown(fake):
    fake.install()
    try:
        # The first look finds the app still up (else _teardown_app returns early); it is gone after.
        calls = []

        def app_procs(prefix, app_id):
            calls.append(app_id)
            return [(999, "AfterFX.exe")] if len(calls) == 1 else []

        N._app_procs = app_procs
        args = argparse.Namespace(app="aftereffects", json=True, force=True, grace=0)
        N._teardown_app(args, "/tmp/pfx", None, {})
    finally:
        fake.restore()


class ThirdParty(unittest.TestCase):
    def test_classification(self):
        fake = Fake({**PROCS, MH[0]: MH[1]})
        fake.install()
        try:
            got = [e for _p, e in N._third_party_procs("/tmp/pfx")]
        finally:
            fake.restore()
        self.assertEqual(got, [MH[1][2]])

    def test_no_sweep_while_third_party_runs(self):
        fake = Fake({**PROCS, MH[0]: MH[1]})
        teardown(fake)
        self.assertFalse(fake.swept, "the prefix was swept under a running third-party program")
        self.assertEqual(fake.emitted["kept_for"], ["ProductManager.exe"])
        self.assertFalse(fake.emitted["swept_prefix"])

    def test_sweep_when_only_leftovers(self):
        fake = Fake(dict(PROCS))
        teardown(fake)
        self.assertTrue(fake.swept, "Adobe/Wine/Microsoft leftovers must still be swept")
        self.assertEqual(fake.emitted["kept_for"], [])


    def test_wine_programs_outside_windows_are_not_third_party(self):
        wine_progs = {
            301: ("iexplore.exe", True, "C:/Program Files/Internet Explorer/iexplore.exe"),
            302: ("iexplore.exe", True, "C:/Program Files (x86)/Internet Explorer/iexplore.exe"),
            303: ("wordpad.exe", True, "C:/Program Files/Windows NT/Accessories/wordpad.exe"),
            304: ("wmplayer.exe", True, "C:/Program Files/Windows Media Player/wmplayer.exe"),
        }
        fake = Fake({**PROCS, **wine_progs})
        fake.install()
        try:
            self.assertEqual(N._third_party_procs("/tmp/pfx"), [])
        finally:
            fake.restore()


class Reprovision(unittest.TestCase):
    """`neutron update` moves every prefix to the new runtime by running `prefix provision` in it, and
    provision closes the prefix's wine session first. A prefix with the Product Manager still
    installing a pack is skipped and named, as one with an Adobe app open is."""

    def run_update(self, procs):
        fake = Fake(procs)
        fake.install()
        saved = {k: getattr(N, k) for k in ("neutron_prefixes", "stamp_mismatch", "mudhut_busy")}
        provisioned = []
        saved_run = N.subprocess.run
        N.neutron_prefixes = lambda: ["/tmp/pfx"]
        N.stamp_mismatch = lambda p, wine: True
        N.mudhut_busy = lambda p: None
        N.subprocess.run = lambda *a, **k: provisioned.append(a) or argparse.Namespace(returncode=0)
        try:
            return N._reprovision_prefixes("11.10-999", True), provisioned
        finally:
            N.subprocess.run = saved_run
            for k, v in saved.items():
                setattr(N, k, v)
            fake.restore()

    def test_skipped_while_third_party_runs(self):
        step, provisioned = self.run_update({**PROCS, MH[0]: MH[1]})
        self.assertEqual(provisioned, [], "the prefix was provisioned under a running third-party program")
        self.assertEqual(step["skipped"], [{"prefix": "/tmp/pfx", "running": ["ProductManager.exe"]}])
        self.assertIn("ProductManager.exe", step["detail"])

    def test_moved_with_only_leftovers(self):
        step, provisioned = self.run_update(dict(PROCS))
        self.assertEqual(len(provisioned), 1)
        self.assertEqual(step["moved"], ["/tmp/pfx"])



class Provision(unittest.TestCase):
    """`prefix provision` (Collider's setup, and every prefix after `neutron update`) closes Adobe's
    leftover helpers before it boots wine. It leaves the session alone while a third-party program
    still runs in it."""

    class Reached(Exception):
        pass

    def provision(self, procs):
        fake = Fake(procs)
        fake.install()
        names = ("resolve_prefix", "resolve_wine", "remember_prefix", "event")
        saved = {k: getattr(N, k) for k in names}
        N.resolve_prefix = lambda path: "/tmp/pfx"
        N.resolve_wine = lambda: ("/usr/bin/wine", True)
        N.remember_prefix = lambda p: None

        def event(*a, **k):
            raise self.Reached()     # the first step after the sweep: stop here
        N.event = event
        try:
            with self.assertRaises(self.Reached):
                N.cmd_prefix_provision(argparse.Namespace(path="/tmp/pfx", prefix=None, json=True))
        finally:
            for k, v in saved.items():
                setattr(N, k, v)
            fake.restore()
        return fake.swept

    def test_no_sweep_while_third_party_runs(self):
        self.assertFalse(self.provision({**PROCS, MH[0]: MH[1]}),
                         "provision closed the session under a running third-party program")

    def test_sweeps_leftovers(self):
        self.assertTrue(self.provision(dict(PROCS)))


if __name__ == "__main__":
    unittest.main()
