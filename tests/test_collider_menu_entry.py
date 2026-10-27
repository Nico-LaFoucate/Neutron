#!/usr/bin/env python3
"""Collider's menu entry names its window class (2026-10-27).

Ubuntu 26.04 VM, the no-terminal install test: Collider launched from its menu entry showed a gear in
GNOME's dock. GNOME ties a window to a .desktop entry by StartupWMClass (or the entry's file name);
Collider's window class is "collider", as in the AppImage's own Collider.desktop, and
neutron-collider.desktop had no StartupWMClass.

Known-bad: NEUTRON_CLI_UNDER_TEST=<pre-fix copy> fails.

Run:  python3 tests/test_collider_menu_entry.py
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


class ColliderEntry(unittest.TestCase):
    def test_names_the_window_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            apps = os.path.join(tmp, "applications")
            appimage = os.path.join(tmp, "Collider.AppImage")
            open(appimage, "w").close()
            with mock.patch.object(N, "APPS_DIR", apps), \
                    mock.patch.object(N, "refresh_desktop_caches", lambda *a: None):
                N._collider_desktop_entry(appimage)
            with open(os.path.join(apps, "neutron-collider.desktop")) as f:
                lines = f.read().splitlines()
            self.assertIn("StartupWMClass=collider", lines)


if __name__ == "__main__":
    unittest.main()
