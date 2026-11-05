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
        self.assertEqual(fake.emitted["kept_for"], [MH[1][2]])
        self.assertFalse(fake.emitted["swept_prefix"])

    def test_sweep_when_only_leftovers(self):
        fake = Fake(dict(PROCS))
        teardown(fake)
        self.assertTrue(fake.swept, "Adobe/Wine/Microsoft leftovers must still be swept")
        self.assertEqual(fake.emitted["kept_for"], [])


if __name__ == "__main__":
    unittest.main()
