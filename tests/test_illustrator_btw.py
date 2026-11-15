#!/usr/bin/env python3
"""Neutron#54 (2026-11-14): "The interface seems choppy/low fps while zooming/moving through the artboad with
spacebar (hand tool)". Illustrator 30.8+ draws its canvas through a Direct3D 12 swap chain, and vkd3d-proton's
blit-to-window read every presented frame back and repainted it through GDI before the next present: hand-tool
panning ran at 8-9 frames/s, 62 with blit-to-window off. The Illustrator profile now sets NEUTRON_DISABLE_BTW=1,
as Photoshop, Lightroom and After Effects do; a caller's NEUTRON_DISABLE_BTW=0 still wins (A/B), and apps that
start Illustrator (Creative Cloud, Bridge) hand it the same setting through neutron-appenv.conf.

The prefixes are synthetic; nothing here starts wine.
Run:  python3 tests/test_illustrator_btw.py
"""
import importlib.machinery
import importlib.util
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


class IllustratorBlitToWindowOff(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-test-ai-btw-")
        self.exe = os.path.join(self.prefix, "drive_c", "Program Files", "Adobe", "Adobe Illustrator 2026",
                                "Support Files", "Contents", "Windows", "Illustrator.exe")
        os.makedirs(os.path.dirname(self.exe))
        open(self.exe, "wb").close()

    def tearDown(self):
        shutil.rmtree(self.prefix, ignore_errors=True)

    def _env(self, env=None, **kw):
        env = {} if env is None else env
        N._apply_app_env(env, "illustrator", N.APP_PROFILES["illustrator"], self.prefix, "x", exe=self.exe, **kw)
        return env

    def test_launch_turns_blit_to_window_off(self):
        self.assertEqual(self._env().get("NEUTRON_DISABLE_BTW"), "1")

    def test_callers_ab_still_wins(self):
        env = self._env({"NEUTRON_DISABLE_BTW": "0"}, protected={"NEUTRON_DISABLE_BTW"})
        self.assertEqual(env["NEUTRON_DISABLE_BTW"], "0")

    def test_photoshop_lightroom_unchanged(self):
        for app in ("photoshop", "lightroom", "aftereffects"):
            self.assertEqual(N.APP_PROFILES[app]["env"].get("NEUTRON_DISABLE_BTW"), "1", app)

    def test_indesign_and_animate_left_alone(self):
        # Not measured for Neutron#54; Animate measured WORSE with it off (2026-08) -- never by association.
        self.assertNotIn("NEUTRON_DISABLE_BTW", N.APP_PROFILES["indesign"]["env"])
        if "animate" in N.APP_PROFILES:
            self.assertNotIn("NEUTRON_DISABLE_BTW", N.APP_PROFILES["animate"].get("env", {}))


if __name__ == "__main__":
    unittest.main()
