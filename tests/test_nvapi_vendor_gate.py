#!/usr/bin/env python3
"""Tests for the NVIDIA-API vendor gate (GitHub Neutron#18, 2026-10-15).

The Photoshop, Lightroom Classic, Lightroom and After Effects profiles export DXVK_ENABLE_NVAPI=1, and the
last three also add the nvapi64=n DLL override. Both exist for NVIDIA GPUs: DXVK reports a fake AMD card in
place of an NVIDIA one unless NVAPI is enabled, and nvapi64 is dxvk-nvapi. On Windows, a machine with only
AMD or Intel GPUs has no nvapi64.dll, so `_apply_app_env` leaves both settings out when the kernel lists GPUs
and none of them is NVIDIA's.

The invariants tested here:
  * any NVIDIA GPU (alone, hybrid, on nouveau), or a GPU list that could not be read: every app's environment
    is exactly what it was before the gate (WINEDLLOVERRIDES is the profile's string, byte for byte);
  * AMD and/or Intel only: those two settings are the ONLY difference, for every app, also in
    neutron-appenv.conf.
Nothing here starts wine; the prefix is a temp dir with empty files where the exes would be.

Run:  python3 tests/test_nvapi_vendor_gate.py
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
# This machine's own NVIDIA driver must not answer for the fake GPU lists below.
N.NVIDIA_PROC_GPUS = os.path.join(tempfile.gettempdir(), "neutron-test-no-such-dir", "gpus")

NVIDIA = [("0x10de", "nvidia")]
WITH_NVIDIA = {
    "nvidia": NVIDIA,
    "intel+nvidia laptop": [("0x8086", "i915"), ("0x10de", "nvidia")],
    "amd+nvidia": [("0x1002", "amdgpu"), ("0x10de", "nvidia")],
    "nvidia on nouveau": [("0x10de", "nouveau")],
    "gpus not readable": [],
}
WITHOUT_NVIDIA = {
    "amd": [("0x1002", "amdgpu")],
    "intel": [("0x8086", "i915")],
    "intel xe": [("0x8086", "xe")],
    "amd+intel": [("0x8086", "i915"), ("0x1002", "amdgpu")],
}
# The four profiles GitHub Neutron#18 names.
NVAPI_APPS = ("photoshop", "lightroom", "lightroomcc", "aftereffects")

EXES = [
    "Program Files/Adobe/Adobe Premiere Pro 2026/Adobe Premiere Pro.exe",
    "Program Files/Adobe/Adobe After Effects 2026/Support Files/AfterFX.exe",
    "Program Files/Adobe/Adobe Photoshop 2026/Photoshop.exe",
    "Program Files/Adobe/Adobe Lightroom Classic/Lightroom.exe",
    "Program Files/Adobe/Adobe Lightroom CC/lightroom.exe",
]


class Helpers(unittest.TestCase):
    def test_nvidia_expected(self):
        for name, gpus in WITH_NVIDIA.items():
            self.assertTrue(N.nvidia_gpu_expected(gpus), name)
        for name, gpus in WITHOUT_NVIDIA.items():
            self.assertFalse(N.nvidia_gpu_expected(gpus), name)

    def test_nvidia_driver_without_a_drm_node_counts(self):
        # The proprietary driver can bind a GPU that has no /sys/class/drm card (nvidia-drm not loaded).
        saved = N.NVIDIA_PROC_GPUS
        root = tempfile.mkdtemp(prefix="neutron-nvproc-")
        try:
            N.NVIDIA_PROC_GPUS = root
            self.assertFalse(N.nvidia_gpu_expected(WITHOUT_NVIDIA["intel"]))     # driver loaded, no GPU
            os.makedirs(os.path.join(root, "0000:01:00.0"))
            self.assertTrue(N.nvidia_gpu_expected(WITHOUT_NVIDIA["intel"]))
        finally:
            N.NVIDIA_PROC_GPUS = saved
            shutil.rmtree(root)

    def test_read_from_a_fake_sysfs(self):
        root = tempfile.mkdtemp(prefix="neutron-drm-")
        try:
            dev = os.path.join(root, "_dev")
            os.makedirs(os.path.join(root, "_drivers", "amdgpu"))
            os.makedirs(dev)
            with open(os.path.join(dev, "vendor"), "w") as f:
                f.write("0x1002\n")
            os.symlink(os.path.join(root, "_drivers", "amdgpu"), os.path.join(dev, "driver"))
            os.makedirs(os.path.join(root, "card0"))
            os.symlink(dev, os.path.join(root, "card0", "device"))
            self.assertEqual(N.drm_gpus(root), [("0x1002", "amdgpu")])
            self.assertFalse(N.nvidia_gpu_expected(N.drm_gpus(root)))
        finally:
            shutil.rmtree(root)

    def test_drop_dll_overrides(self):
        drop = N._drop_dll_overrides
        nv = N.NVIDIA_ONLY_DLL_OVERRIDES
        self.assertEqual(drop("ucrtbase=n,b;dwrite=b;nvapi64=n;dcomp=n,b", nv), "ucrtbase=n,b;dwrite=b;dcomp=n,b")
        self.assertEqual(drop("ucrtbase=n,b;dwrite=b;nvapi64=n", nv), "ucrtbase=n,b;dwrite=b")
        self.assertEqual(drop("nvapi64=n", nv), "")
        self.assertEqual(drop("NVAPI64=n;dwrite=b", nv), "dwrite=b")
        self.assertEqual(drop("nvapi64,dxgi=n;;dwrite=b", nv), "dxgi=n;dwrite=b")
        self.assertEqual(drop("dwrite=b", nv), "dwrite=b")
        self.assertEqual(drop("", nv), "")


class ProfileEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = os.path.join(self.tmp.name, "Adobe")
        for rel in EXES:
            p = os.path.join(self.prefix, "drive_c", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        self._drm_gpus = N.drm_gpus

    def tearDown(self):
        N.drm_gpus = self._drm_gpus
        self.tmp.cleanup()

    def env(self, app, gpus, start=None):
        e = dict(start or {})
        N._apply_app_env(e, app, N.APP_PROFILES[app], self.prefix, "x.conf", gpus=gpus)
        return e

    def test_the_profiles_still_carry_the_nvidia_settings(self):
        # Otherwise every test below would pass without testing anything.
        for app in NVAPI_APPS:
            self.assertTrue(N.APP_PROFILES[app]["nvapi"], app)
        for app in ("lightroom", "lightroomcc", "aftereffects"):
            self.assertIn("nvapi64=n", N.APP_PROFILES[app]["overrides"], app)

    def test_nvidia_machines_get_the_profile_unchanged(self):
        for app, profile in N.APP_PROFILES.items():
            want = self.env(app, NVIDIA)
            self.assertEqual(want.get("WINEDLLOVERRIDES"), profile["overrides"] or None, app)
            self.assertEqual(want.get("DXVK_ENABLE_NVAPI"), "1" if profile["nvapi"] else None, app)
            for name, gpus in WITH_NVIDIA.items():
                self.assertEqual(self.env(app, gpus), want, "%s on %s" % (app, name))

    def test_amd_and_intel_lose_only_the_two_settings(self):
        for app, profile in N.APP_PROFILES.items():
            nv = self.env(app, NVIDIA)
            for name, gpus in WITHOUT_NVIDIA.items():
                got = self.env(app, gpus)
                self.assertNotIn("DXVK_ENABLE_NVAPI", got, "%s on %s" % (app, name))
                self.assertNotIn("nvapi64", got.get("WINEDLLOVERRIDES", "").lower(), "%s on %s" % (app, name))
                want = dict(nv)
                want.pop("DXVK_ENABLE_NVAPI", None)
                ovr = N._drop_dll_overrides(profile["overrides"], N.NVIDIA_ONLY_DLL_OVERRIDES)
                if ovr:
                    want["WINEDLLOVERRIDES"] = ovr
                else:
                    want.pop("WINEDLLOVERRIDES", None)
                self.assertEqual(got, want, "%s on %s" % (app, name))

    def test_issue_18_apps_by_name_on_amd(self):
        amd = WITHOUT_NVIDIA["amd"]
        self.assertEqual(self.env("photoshop", amd)["WINEDLLOVERRIDES"], "dwrite=b")
        self.assertEqual(self.env("lightroom", amd)["WINEDLLOVERRIDES"], "ucrtbase=n,b;dwrite=b;dcomp=n,b")
        self.assertEqual(self.env("lightroomcc", amd)["WINEDLLOVERRIDES"], "ucrtbase=n,b;dwrite=b;dcomp=n,b")
        self.assertEqual(self.env("aftereffects", amd)["WINEDLLOVERRIDES"], "ucrtbase=n,b;dwrite=b")
        for app in NVAPI_APPS:
            self.assertNotIn("DXVK_ENABLE_NVAPI", self.env(app, amd), app)
            self.assertEqual(self.env(app, NVIDIA)["DXVK_ENABLE_NVAPI"], "1", app)

    def test_prefix_and_caller_overrides_survive_on_amd(self):
        with open(os.path.join(self.prefix, "neutron-env.conf"), "w") as f:
            f.write("WINEDLLOVERRIDES=foo=d\n")
        got = self.env("aftereffects", WITHOUT_NVIDIA["amd"])
        self.assertEqual(got["WINEDLLOVERRIDES"], "foo=d;ucrtbase=n,b;dwrite=b")

    def test_a_value_the_caller_set_is_left_alone(self):
        # The gate stops ADDING the variable; it never removes one the user chose to set.
        got = self.env("photoshop", WITHOUT_NVIDIA["amd"], start={"DXVK_ENABLE_NVAPI": "1"})
        self.assertEqual(got["DXVK_ENABLE_NVAPI"], "1")

    def test_gpus_are_read_when_not_given(self):
        N.drm_gpus = lambda *a, **k: list(WITHOUT_NVIDIA["amd"])
        e = {}
        N._apply_app_env(e, "aftereffects", N.APP_PROFILES["aftereffects"], self.prefix, "x.conf")
        self.assertNotIn("DXVK_ENABLE_NVAPI", e)
        N.drm_gpus = lambda *a, **k: list(NVIDIA)
        e = {}
        N._apply_app_env(e, "aftereffects", N.APP_PROFILES["aftereffects"], self.prefix, "x.conf")
        self.assertEqual(e["DXVK_ENABLE_NVAPI"], "1")

    def test_appenv_conf_follows_the_gpu(self):
        path = os.path.join(self.prefix, N.APPENV_CONF)
        N.drm_gpus = lambda *a, **k: list(WITHOUT_NVIDIA["amd"])
        N.write_appenv_conf(self.prefix)
        with open(path) as f:
            amd = f.read()
        self.assertNotIn("DXVK_ENABLE_NVAPI", amd)
        self.assertNotIn("nvapi64", amd)
        N.drm_gpus = lambda *a, **k: list(NVIDIA)
        N.write_appenv_conf(self.prefix)
        with open(path) as f:
            nv = f.read()
        self.assertIn("DXVK_ENABLE_NVAPI=1", nv)
        self.assertIn("-DXVK_ENABLE_NVAPI", nv)       # Premiere's section clears AE's value
        self.assertIn("nvapi64=n", nv)


if __name__ == "__main__":
    unittest.main()
