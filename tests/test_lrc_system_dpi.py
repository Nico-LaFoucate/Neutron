#!/usr/bin/env python3
"""Tests for Lightroom Classic's "System" high-DPI setting (2026-10-21).

Lightroom Classic takes its UI scale once, at launch, and ignores the scale-change message, so on a 100% screen beside a
175% one it came up at the wrong scale whenever the compositor opened it on the other screen, and kept it when moved.
Windows gives such an app the right size on every screen with its "System" high-DPI override, kept under
HKCU\\...\\AppCompatFlags\\Layers. `ensure_lightroom_system_dpi()` writes that value for a prefix with Lightroom Classic
and leaves a value the user already has alone. Nothing here starts wine: reg_set is replaced by a recorder.

Run:  python3 tests/test_lrc_system_dpi.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()

USER_REG = "WINE REGISTRY Version 2\n;; All keys relative to \\\\User\\\\S-1-5-21-0-0-0-1000\n\n#arch=win64\n\n"
LAYERS = "[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\AppCompatFlags\\\\Layers] 1792555576\n"


class LightroomSystemDpi(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-lrcdpi-")
        self.writes = []
        self.patch = mock.patch.object(N, "reg_set", lambda wine, prefix, key, name, vtype, data:
                                       self.writes.append((prefix, key, name, vtype, data)))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.prefix)

    def install(self):
        d = os.path.join(self.prefix, "drive_c", "Program Files", "Adobe", "Adobe Lightroom Classic")
        os.makedirs(d)
        open(os.path.join(d, "Lightroom.exe"), "w").close()

    def user_reg(self, body=""):
        with open(os.path.join(self.prefix, "user.reg"), "w") as f:
            f.write(USER_REG + body)

    def test_no_lightroom_writes_nothing(self):
        self.user_reg()
        self.assertIsNone(N.ensure_lightroom_system_dpi("/wine", self.prefix))
        self.assertEqual(self.writes, [])

    def test_lightroom_gets_the_value(self):
        self.install()
        self.user_reg()
        self.assertEqual(N.ensure_lightroom_system_dpi("/wine", self.prefix), "added")
        self.assertEqual(self.writes, [(self.prefix,
                                        "HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers",
                                        "lightroom.exe", "REG_SZ", "~ HIGHDPIAWARE")])

    def test_other_apps_layers_do_not_count(self):
        self.install()
        self.user_reg(LAYERS + '"photoshop.exe"="~ RUNASADMIN"\n\n')
        self.assertEqual(N.ensure_lightroom_system_dpi("/wine", self.prefix), "added")
        self.assertEqual(len(self.writes), 1)

    def test_users_own_value_is_kept(self):
        self.install()
        self.user_reg(LAYERS + '"Lightroom.exe"="~ DPIUNAWARE"\n\n')
        self.assertEqual(N.ensure_lightroom_system_dpi("/wine", self.prefix), "kept")
        self.assertEqual(self.writes, [])

    def test_already_set_is_not_rewritten(self):
        self.install()
        self.user_reg(LAYERS + '"lightroom.exe"="~ HIGHDPIAWARE"\n\n')
        self.assertEqual(N.ensure_lightroom_system_dpi("/wine", self.prefix), "kept")
        self.assertEqual(self.writes, [])

    def test_unreadable_user_reg_writes_nothing(self):
        self.install()
        self.assertIsNone(N.ensure_lightroom_system_dpi("/wine", self.prefix))
        self.assertEqual(self.writes, [])

    def test_launch_and_provision_both_apply_it(self):
        with open(_CLI) as f:
            src = f.read()
        launch = src[src.index("def cmd_launch("):]
        launch = launch[:launch.index("\ndef ")]
        self.assertIn("ensure_lightroom_system_dpi(wine, prefix)", launch)
        self.assertIn('"step": "lrc_system_dpi"', src)

    def test_gates_list_the_141_switches(self):
        envs = {g["env"] for g in N.NEUTRON_GATES.values()}
        for env in ("NEUTRON_CREATE_TARGET_DPI", "NEUTRON_DPICHG_SKIP_UNPLACED", "NEUTRON_NORMAL_FOLLOWS_MONITOR",
                    "NEUTRON_SURFACE_CROP_DPI", "NEUTRON_RAW_WINDOW_MONITOR", "NEUTRON_ATTACH_DEST",
                    "NEUTRON_WORKAREA_GUARD"):
            self.assertIn(env, envs)


if __name__ == "__main__":
    unittest.main()
