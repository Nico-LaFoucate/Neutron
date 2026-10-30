#!/usr/bin/env python3
"""Tests for `prefix provision` letting Camera Raw test its GPU again (bin/neutron: _retest_failed_camera_raw_gpu).

Camera Raw caches its GPU self-test result in AppData/Roaming/Adobe/CameraRaw/GPU/<host>/Camera Raw GPU Config.txt and
never tests again while it says the test failed (2026-10-29: every Photoshop prefix on the dev box carried a failure
cached by an older runtime; the test passes on current runtimes). Provision moves a cached failure aside, leaves a
passing result alone, and does nothing more on later runs. The prefixes are synthetic; nothing here starts wine.

Run:  python3 tests/test_camera_raw_gpu_retest.py
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


CLI = _load_cli()
CONFIG = '<x:xmpmeta>\n   crs:gpu_compute_quick_self_test_passed="%s"\n</x:xmpmeta>\n'


class CameraRawGpuRetest(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-crgpu-")
        self.gpu = os.path.join(self.prefix, "drive_c", "users", "artist", "AppData", "Roaming", "Adobe",
                                "CameraRaw", "GPU")
        os.makedirs(os.path.join(self.prefix, "drive_c", "users", "Public"))
        self._env = os.environ.get("USER")
        os.environ["USER"] = "artist"

    def tearDown(self):
        shutil.rmtree(self.prefix)
        if self._env is None:
            os.environ.pop("USER", None)
        else:
            os.environ["USER"] = self._env

    def host(self, name, passed):
        d = os.path.join(self.gpu, name)
        os.makedirs(d)
        with open(os.path.join(d, "Camera Raw GPU Config.txt"), "w") as f:
            f.write(CONFIG % passed)

    def test_failed_result_is_set_aside_and_passing_one_kept(self):
        self.host("Adobe Photoshop Camera Raw", "False")
        self.host("Adobe Photoshop Lightroom Classic", "True")
        self.assertEqual(CLI._retest_failed_camera_raw_gpu(self.prefix), ["Adobe Photoshop Camera Raw"])
        left = sorted(os.listdir(self.gpu))
        self.assertIn("Adobe Photoshop Lightroom Classic", left)
        self.assertNotIn("Adobe Photoshop Camera Raw", left)
        self.assertTrue(any(n.startswith("Adobe Photoshop Camera Raw.failed-") for n in left))

    def test_second_run_changes_nothing(self):
        self.host("Adobe Photoshop Camera Raw", "False")
        CLI._retest_failed_camera_raw_gpu(self.prefix)
        before = sorted(os.listdir(self.gpu))
        self.assertEqual(CLI._retest_failed_camera_raw_gpu(self.prefix), [])
        self.assertEqual(sorted(os.listdir(self.gpu)), before)

    def test_no_camera_raw_folder_is_fine(self):
        self.assertEqual(CLI._retest_failed_camera_raw_gpu(self.prefix), [])


if __name__ == "__main__":
    unittest.main()
