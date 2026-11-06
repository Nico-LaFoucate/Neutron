#!/usr/bin/env python3
"""Tests for the CUDA-only profile variables (GitHub Neutron#47, 2026-11-06).

The After Effects profile sets NEUTRON_DXVK_EXPORT_TEXTURES=1: our DXVK then marks interop-shaped textures
(2D, >=512x512, BIND_UNORDERED_ACCESS, GPU-only) shared, so our nvcuda can hand their memory to CUDA
(cuGraphicsD3D11RegisterResource). On a machine without a GPU on NVIDIA's own driver there is no CUDA:
After Effects renders through OpenCL, nothing registers those textures, and the forced sharing only changes
what After Effects sees (GetDesc returns MiscFlags SHARED|SHARED_NTHANDLE for a texture it created plain).
`_apply_app_env` leaves the CUDA_ONLY_ENV variables out when cuda_gpu_expected() is False.

The invariants tested here:
  * a GPU on NVIDIA's own driver (alone, hybrid laptop, next to AMD, or bound with no DRM node), or a GPU list
    that could not be read: After Effects keeps NEUTRON_DXVK_EXPORT_TEXTURES=1, every app's environment is
    exactly what it was before;
  * AMD, Intel, or NVIDIA on nouveau: the CUDA-only variables are the ONLY difference, for every app, also in
    neutron-appenv.conf;
  * a value the caller or neutron-env.conf sets is never dropped.
Nothing here starts wine; the prefix is a temp dir with empty files where the exes would be.

Run:  python3 tests/test_cuda_only_env.py
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

KEY = "NEUTRON_DXVK_EXPORT_TEXTURES"
NVIDIA = [("0x10de", "nvidia")]
WITH_CUDA = {
    "nvidia": NVIDIA,
    "intel+nvidia laptop": [("0x8086", "i915"), ("0x10de", "nvidia")],
    "amd+nvidia laptop": [("0x1002", "amdgpu"), ("0x10de", "nvidia")],
    "gpus not readable": [],
}
WITHOUT_CUDA = {
    "amd": [("0x1002", "amdgpu")],                       # the Neutron#47 reporter: RX 7600 XT, ROCm OpenCL
    "intel": [("0x8086", "i915")],
    "intel xe": [("0x8086", "xe")],
    "amd+intel": [("0x8086", "i915"), ("0x1002", "amdgpu")],
    "nvidia on nouveau": [("0x10de", "nouveau")],
    "intel+nvidia on nouveau": [("0x8086", "i915"), ("0x10de", "nouveau")],
}

EXES = [
    "Program Files/Adobe/Adobe Premiere Pro 2026/Adobe Premiere Pro.exe",
    "Program Files/Adobe/Adobe After Effects 2026/Support Files/AfterFX.exe",
    "Program Files/Adobe/Adobe Photoshop 2026/Photoshop.exe",
    "Program Files/Adobe/Adobe Lightroom Classic/Lightroom.exe",
    "Program Files/Adobe/Adobe Lightroom CC/lightroom.exe",
]


class Helper(unittest.TestCase):
    def test_cuda_expected(self):
        for name, gpus in WITH_CUDA.items():
            self.assertTrue(N.cuda_gpu_expected(gpus), name)
        for name, gpus in WITHOUT_CUDA.items():
            self.assertFalse(N.cuda_gpu_expected(gpus), name)

    def test_nvidia_driver_without_a_drm_node_counts(self):
        # NVIDIA's driver can bind a GPU that has no /sys/class/drm card (nvidia-drm not loaded); CUDA works there.
        saved = N.NVIDIA_PROC_GPUS
        root = tempfile.mkdtemp(prefix="neutron-nvproc-")
        try:
            N.NVIDIA_PROC_GPUS = root
            self.assertFalse(N.cuda_gpu_expected(WITHOUT_CUDA["intel"]))      # driver loaded, no GPU
            os.makedirs(os.path.join(root, "0000:01:00.0"))
            self.assertTrue(N.cuda_gpu_expected(WITHOUT_CUDA["intel"]))
        finally:
            N.NVIDIA_PROC_GPUS = saved
            shutil.rmtree(root)

    def test_the_gate_names_what_the_profile_sets(self):
        # Otherwise every test below would pass without testing anything.
        self.assertIn(KEY, N.CUDA_ONLY_ENV)
        self.assertEqual(N.APP_PROFILES["aftereffects"]["env"].get(KEY), "1")
        for key in N.CUDA_ONLY_ENV:
            self.assertTrue(any(key in p.get("env", {}) for p in N.APP_PROFILES.values()), key)


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

    def test_cuda_machines_keep_the_export_gate(self):
        for name, gpus in WITH_CUDA.items():
            self.assertEqual(self.env("aftereffects", gpus).get(KEY), "1", name)

    def test_machines_without_cuda_lose_only_the_cuda_only_variables(self):
        for app in N.APP_PROFILES:
            for name, gpus in WITHOUT_CUDA.items():
                got = self.env(app, gpus)
                for key in N.CUDA_ONLY_ENV:
                    self.assertNotIn(key, got, "%s on %s" % (app, name))
                # Same GPU list with CUDA_ONLY_ENV empty = what the CLI gave before the gate.
                saved = N.CUDA_ONLY_ENV
                try:
                    N.CUDA_ONLY_ENV = ()
                    want = self.env(app, gpus)
                finally:
                    N.CUDA_ONLY_ENV = saved
                for key in saved:
                    want.pop(key, None)
                self.assertEqual(got, want, "%s on %s" % (app, name))

    def test_rest_of_the_after_effects_profile_still_applies_on_amd(self):
        got = self.env("aftereffects", WITHOUT_CUDA["amd"])
        for k, v in N.APP_PROFILES["aftereffects"]["env"].items():
            if k not in N.CUDA_ONLY_ENV:
                self.assertEqual(got.get(k), v, k)

    def test_a_value_the_caller_set_is_left_alone(self):
        # The gate stops ADDING the variable; it never removes or changes one the user chose to set.
        self.assertEqual(self.env("aftereffects", WITHOUT_CUDA["amd"], start={KEY: "1"})[KEY], "1")
        self.assertEqual(self.env("aftereffects", NVIDIA, start={KEY: "0"})[KEY], "0")

    def test_prefix_env_conf_still_applies_on_amd(self):
        with open(os.path.join(self.prefix, "neutron-env.conf"), "w") as f:
            f.write("%s=1\n" % KEY)
        self.assertEqual(self.env("aftereffects", WITHOUT_CUDA["amd"])[KEY], "1")

    def test_gpus_are_read_when_not_given(self):
        N.drm_gpus = lambda *a, **k: list(WITHOUT_CUDA["amd"])
        e = {}
        N._apply_app_env(e, "aftereffects", N.APP_PROFILES["aftereffects"], self.prefix, "x.conf")
        self.assertNotIn(KEY, e)
        N.drm_gpus = lambda *a, **k: list(NVIDIA)
        e = {}
        N._apply_app_env(e, "aftereffects", N.APP_PROFILES["aftereffects"], self.prefix, "x.conf")
        self.assertEqual(e[KEY], "1")

    def test_appenv_conf_follows_the_gpu(self):
        # An After Effects started by another app (Dynamic Link) gets what a direct launch gives it.
        path = os.path.join(self.prefix, N.APPENV_CONF)
        N.drm_gpus = lambda *a, **k: list(WITHOUT_CUDA["amd"])
        N.write_appenv_conf(self.prefix)
        with open(path) as f:
            amd = f.read()
        self.assertNotIn(KEY, amd)
        N.drm_gpus = lambda *a, **k: list(NVIDIA)
        N.write_appenv_conf(self.prefix)
        with open(path) as f:
            nv = f.read()
        self.assertIn("%s=1" % KEY, nv)
        self.assertIn("-%s" % KEY, nv)                 # Premiere's section clears After Effects' value


if __name__ == "__main__":
    unittest.main()
