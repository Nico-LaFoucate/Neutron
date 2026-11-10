#!/usr/bin/env python3
"""Tests for the Adobe GPU filter on NVIDIA + other-vendor machines (2026-11-10, GitHub Neutron#49).

On a laptop whose NVIDIA GPU runs NVIDIA's own driver next to another vendor's GPU, `_apply_app_env` gives every Adobe
app DXVK_FILTER_DEVICE_NAME and VKD3D_FILTER_DEVICE_NAME = HYBRID_ADOBE_GPU_FILTER, so DXVK and vkd3d-proton show it only
the NVIDIA GPU. The invariants tested here:
  * AMD or Intel iGPU + NVIDIA on nvidia: every Adobe app gets both variables;
  * NVIDIA alone, AMD alone, Intel alone, NVIDIA on nouveau next to an iGPU, GPUs not readable: neither variable;
  * a value the caller set (or protected) is left alone;
  * a program (not an Adobe app profile) gets neither.
Nothing here starts wine.

Run:  python3 tests/test_hybrid_adobe_gpu_filter.py
"""
import importlib.machinery
import importlib.util
import os
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
N.NVIDIA_PROC_GPUS = os.path.join(tempfile.gettempdir(), "neutron-test-no-such-dir", "gpus")

VARS = N.HYBRID_ADOBE_GPU_FILTER_VARS
HYBRID = {
    "amd+nvidia laptop": [("0x1002", "amdgpu"), ("0x10de", "nvidia")],
    "intel+nvidia laptop": [("0x8086", "i915"), ("0x10de", "nvidia")],
    "intel xe+nvidia laptop": [("0x8086", "xe"), ("0x10de", "nvidia")],
}
NOT_HYBRID = {
    "nvidia": [("0x10de", "nvidia")],
    "amd": [("0x1002", "amdgpu")],
    "intel": [("0x8086", "i915")],
    "intel+nvidia on nouveau": [("0x8086", "i915"), ("0x10de", "nouveau")],
    "gpus not readable": [],
}


class AdobeGpuFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = os.path.join(self.tmp.name, "Adobe")
        os.makedirs(os.path.join(self.prefix, "drive_c"))

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, app, gpus, start=None, protected=(), profile=None):
        e = dict(start or {})
        N._apply_app_env(e, app, profile or N.APP_PROFILES[app], self.prefix, "x.conf", protected=protected, gpus=gpus)
        return e

    def test_every_adobe_app_on_a_hybrid_sees_only_nvidia(self):
        for name, gpus in HYBRID.items():
            for app in N.APP_PROFILES:
                e = self.env(app, gpus)
                for var in VARS:
                    self.assertEqual(e.get(var), N.HYBRID_ADOBE_GPU_FILTER, (name, app, var))

    def test_other_machines_get_no_filter(self):
        for name, gpus in NOT_HYBRID.items():
            for app in N.APP_PROFILES:
                e = self.env(app, gpus)
                for var in VARS:
                    self.assertNotIn(var, e, (name, app, var))

    def test_a_value_the_caller_set_wins(self):
        e = self.env("premiere", HYBRID["amd+nvidia laptop"], start={"DXVK_FILTER_DEVICE_NAME": "RTX"},
                     protected={"DXVK_FILTER_DEVICE_NAME"})
        self.assertEqual(e["DXVK_FILTER_DEVICE_NAME"], "RTX")
        self.assertEqual(e["VKD3D_FILTER_DEVICE_NAME"], N.HYBRID_ADOBE_GPU_FILTER)

    def test_a_program_gets_no_filter(self):
        e = self.env("program-capcut", HYBRID["amd+nvidia laptop"], profile=dict(N.APP_PROFILES["premiere"]))
        for var in VARS:
            self.assertNotIn(var, e, var)

    def test_the_filter_names_only_the_nvidia_device(self):
        self.assertIn(N.HYBRID_ADOBE_GPU_FILTER, "NVIDIA GeForce RTX 5050 Laptop GPU")
        self.assertNotIn(N.HYBRID_ADOBE_GPU_FILTER, "AMD Radeon 760M Graphics (RADV PHOENIX)")
        self.assertNotIn(N.HYBRID_ADOBE_GPU_FILTER, "Intel(R) Graphics (ADL GT2)")


if __name__ == "__main__":
    unittest.main()
