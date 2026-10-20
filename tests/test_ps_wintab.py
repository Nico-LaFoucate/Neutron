#!/usr/bin/env python3
"""Tests for the Photoshop pen setting (2026-10-20, GitHub neutron-wine#1).

Photoshop reads a pen through WinTab only when its PSUserConfig.txt says `UseSystemStylus 0`; otherwise it uses Windows
Ink, which under Wine gives no pressure. On the operator's Cintiq 22HD, Photoshop 2026 without the line never loaded
WinTab32.dll and drew without pressure; with it, pressure worked. `ensure_photoshop_wintab()` writes the line for every
installed Photoshop and leaves a user's own UseSystemStylus line alone. Nothing here starts wine; the prefix is a temp dir.

Run:  python3 tests/test_ps_wintab.py
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


class PhotoshopWintab(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-pswt-")
        os.makedirs(os.path.join(self.prefix, "drive_c", "users", "tester", "AppData", "Roaming", "Adobe"))
        self.env = mock.patch.dict(os.environ, {"USER": "tester"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.prefix)

    def install(self, name):
        inst = os.path.join(self.prefix, "drive_c", "Program Files", "Adobe", name)
        os.makedirs(inst)
        open(os.path.join(inst, "Photoshop.exe"), "w").close()

    def config(self, name):
        return os.path.join(self.prefix, "drive_c", "users", "tester", "AppData", "Roaming", "Adobe", name,
                            name + " Settings", "PSUserConfig.txt")

    def read(self, name):
        with open(self.config(name), newline="") as f:
            return f.read()

    def test_new_install_gets_the_line(self):
        self.install("Adobe Photoshop 2026")
        self.assertEqual(N.ensure_photoshop_wintab(self.prefix), [("Adobe Photoshop 2026", "added")])
        self.assertIn("\r\nUseSystemStylus 0\r\n", self.read("Adobe Photoshop 2026"))

    def test_every_photoshop_and_nothing_else(self):
        self.install("Adobe Photoshop 2025")
        self.install("Adobe Photoshop 2026")
        os.makedirs(os.path.join(self.prefix, "drive_c", "Program Files", "Adobe", "Adobe Illustrator 2026"))
        got = N.ensure_photoshop_wintab(self.prefix)
        self.assertEqual(got, [("Adobe Photoshop 2025", "added"), ("Adobe Photoshop 2026", "added")])

    def test_existing_settings_are_kept(self):
        self.install("Adobe Photoshop 2025")
        os.makedirs(os.path.dirname(self.config("Adobe Photoshop 2025")))
        with open(self.config("Adobe Photoshop 2025"), "w", newline="") as f:
            f.write("GPUDeny 0\r\nGPUForce 1")          # no trailing newline, as on the operator's 2025 prefix
        N.ensure_photoshop_wintab(self.prefix)
        self.assertEqual(self.read("Adobe Photoshop 2025"),
                         "GPUDeny 0\r\nGPUForce 1\r\n"
                         "# Neutron: read the pen through WinTab (pressure, tilt, eraser)\r\nUseSystemStylus 0\r\n")

    def test_users_own_choice_is_left_alone(self):
        self.install("Adobe Photoshop 2026")
        os.makedirs(os.path.dirname(self.config("Adobe Photoshop 2026")))
        with open(self.config("Adobe Photoshop 2026"), "w") as f:
            f.write("useSystemStylus 1\n")
        self.assertEqual(N.ensure_photoshop_wintab(self.prefix), [("Adobe Photoshop 2026", "kept")])
        self.assertEqual(self.read("Adobe Photoshop 2026"), "useSystemStylus 1\n")

    def test_second_run_changes_nothing(self):
        self.install("Adobe Photoshop 2026")
        N.ensure_photoshop_wintab(self.prefix)
        first = self.read("Adobe Photoshop 2026")
        self.assertEqual(N.ensure_photoshop_wintab(self.prefix), [("Adobe Photoshop 2026", "kept")])
        self.assertEqual(self.read("Adobe Photoshop 2026"), first)

    def test_prefix_without_photoshop(self):
        self.assertEqual(N.ensure_photoshop_wintab(self.prefix), [])
        self.assertEqual(N.ensure_photoshop_wintab(os.path.join(self.prefix, "missing")), [])


if __name__ == "__main__":
    unittest.main()
