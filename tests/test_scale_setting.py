#!/usr/bin/env python3
"""Tests for the launch display scale: --scale, then Collider's manual setting, then the desktop.

GitHub Neutron#16 (2026-10-12): Collider's Preferences > Display scale was applied only to the
launches Collider started (it passed --scale). A desktop-icon launch ran `neutron launch premiere`
without it and detected the desktop's scale again, so "100%" in Collider did nothing there.
`resolve_launch_scale` is now the one place every launch gets its scale from.

Run:  python3 tests/test_scale_setting.py
"""
import importlib.machinery
import importlib.util
import json
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
DESKTOP = {"scale": 1.25, "source": "gnome", "output": "DP-1", "dpi": 120, "windows_step": True}


class ScaleSetting(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="neutron-scale-")
        self._home, self._detect = N.HOME, N.detect_scale_info
        N.HOME = self.home
        N.detect_scale_info = lambda: dict(DESKTOP)

    def tearDown(self):
        N.HOME, N.detect_scale_info = self._home, self._detect
        shutil.rmtree(self.home, ignore_errors=True)

    def collider(self, text):
        d = os.path.join(self.home, ".config", "collider")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))

    def test_manual_setting_applies_without_scale_flag(self):
        # The #16 case: Collider at 100% on a 125% desktop, launched from the desktop icon.
        self.collider({"scale_mode": "manual", "scale_value": 1.0, "selected_prefix": "/x"})
        self.assertEqual(N.collider_manual_scale(), 1.0)
        self.assertEqual(N.resolve_launch_scale(None), (1.0, "collider setting"))

    def test_scale_flag_wins(self):
        self.collider({"scale_mode": "manual", "scale_value": 1.0})
        self.assertEqual(N.resolve_launch_scale(1.5), (1.5, "--scale"))

    def test_auto_mode_uses_the_desktop(self):
        self.collider({"scale_mode": "auto", "scale_value": 1.0})
        self.assertIsNone(N.collider_manual_scale())
        self.assertEqual(N.resolve_launch_scale(None), (1.25, "gnome"))

    def test_no_collider_config_uses_the_desktop(self):
        self.assertIsNone(N.collider_manual_scale())
        self.assertEqual(N.resolve_launch_scale(None), (1.25, "gnome"))

    def test_unusable_settings_mean_not_set(self):
        for bad in ({"scale_mode": "manual", "scale_value": None},
                    {"scale_mode": "manual"},
                    {"scale_mode": "manual", "scale_value": 0},
                    {"scale_mode": "manual", "scale_value": 20},
                    {"scale_mode": "manual", "scale_value": "big"},
                    "{not json"):
            self.collider(bad)
            self.assertIsNone(N.collider_manual_scale(), bad)
            self.assertEqual(N.resolve_launch_scale(None), (1.25, "gnome"), bad)

    def test_nothing_known(self):
        N.detect_scale_info = lambda: None
        self.assertEqual(N.resolve_launch_scale(None), (None, None))


if __name__ == "__main__":
    unittest.main()
