#!/usr/bin/env python3
"""Tests for the EGL/GLX vendor gate (AMD support audit X5, 2026-10-15).

`launch` used to force NVIDIA's EGL and GLX vendor (__EGL_VENDOR_LIBRARY_FILENAMES=10_nvidia.json,
__GLX_VENDOR_LIBRARY_NAME=nvidia) whenever NVIDIA's EGL vendor FILE existed, whatever GPU the machine had.
An AMD or Intel machine with NVIDIA's userspace still installed then lost Mesa's EGL, and with it Wine's
OpenGL. `_apply_gl_vendor_env` now forces it only when the file exists AND an NVIDIA GPU is in use
(`nvidia_gpu_expected`, the same predicate as the NVIDIA-API gate).

The invariants tested here:
  * any NVIDIA GPU (alone, hybrid, on nouveau, bound with no DRM node), or a GPU list that could not be
    read: exactly what the pre-gate code produced, PRIME render offload included;
  * AMD and/or Intel only: no NVIDIA vendor variables, file or no file;
  * a value the caller set is never touched;
  * `cmd_launch` goes through the helper (no second, ungated copy of the rule).

Run:  python3 tests/test_egl_vendor_gate.py
"""
import importlib.machinery
import importlib.util
import inspect
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

NV, IN, AM = "0x10de", "0x8086", "0x1002"
# name -> (gpus, boot vendor)
WITH_NVIDIA = {
    "nvidia": ([(NV, "nvidia")], NV),
    "intel+nvidia laptop": ([(IN, "i915"), (NV, "nvidia")], IN),
    "intel+nvidia desktop": ([(IN, "i915"), (NV, "nvidia")], NV),
    "amd apu+nvidia laptop": ([(AM, "amdgpu"), (NV, "nvidia")], AM),
    "hybrid, no boot_vga": ([(AM, "amdgpu"), (NV, "nvidia")], None),
    "nvidia on nouveau": ([(NV, "nouveau")], NV),
    "gpus not readable": ([], None),
}
WITHOUT_NVIDIA = {
    "amd": ([(AM, "amdgpu")], AM),
    "intel": ([(IN, "i915")], IN),
    "intel xe": ([(IN, "xe")], IN),
    "amd+intel": ([(IN, "i915"), (AM, "amdgpu")], IN),
}
KEYS = ("__EGL_VENDOR_LIBRARY_FILENAMES", "__GLX_VENDOR_LIBRARY_NAME", "__NV_PRIME_RENDER_OFFLOAD")


def pre_gate(env, gpus, boot, icd):
    """The rule as it was in CLI 1.0.0-beta.12 (bin/neutron cmd_launch), for comparison."""
    if os.path.isfile(icd):
        env.setdefault("__EGL_VENDOR_LIBRARY_FILENAMES", icd)
        env.setdefault("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
        if N.nvidia_render_offload(gpus, boot):
            env.setdefault("__NV_PRIME_RENDER_OFFLOAD", "1")


class EglVendorGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutron-egl-")
        self.icd = os.path.join(self.tmp, "10_nvidia.json")
        open(self.icd, "w").close()
        self.saved = (N.NVIDIA_EGL_ICD, N.NVIDIA_PROC_GPUS, N.boot_gpu_vendor)
        N.NVIDIA_EGL_ICD = self.icd
        # this machine's own NVIDIA driver must not answer for the fake GPU lists
        N.NVIDIA_PROC_GPUS = os.path.join(self.tmp, "no-such-dir")

    def tearDown(self):
        N.NVIDIA_EGL_ICD, N.NVIDIA_PROC_GPUS, N.boot_gpu_vendor = self.saved
        shutil.rmtree(self.tmp)

    def apply(self, gpus, boot, start=None):
        N.boot_gpu_vendor = lambda *a, **k: boot
        env = dict(start or {})
        forced = N._apply_gl_vendor_env(env, gpus)
        return env, forced

    def test_nvidia_machines_match_the_pre_gate_rule(self):
        for icd_present in (True, False):
            if not icd_present:
                os.remove(self.icd)
            for name, (gpus, boot) in WITH_NVIDIA.items():
                got, forced = self.apply(gpus, boot)
                want = {}
                pre_gate(want, gpus, boot, self.icd)
                self.assertEqual(got, want, "%s, icd file %s" % (name, icd_present))
                self.assertEqual(forced, icd_present, name)

    def test_nvidia_values(self):
        got, _ = self.apply(*WITH_NVIDIA["nvidia"])
        self.assertEqual(got, {"__EGL_VENDOR_LIBRARY_FILENAMES": self.icd,
                               "__GLX_VENDOR_LIBRARY_NAME": "nvidia"})
        got, _ = self.apply(*WITH_NVIDIA["intel+nvidia laptop"])
        self.assertEqual(got.get("__NV_PRIME_RENDER_OFFLOAD"), "1")
        got, _ = self.apply(*WITH_NVIDIA["intel+nvidia desktop"])
        self.assertNotIn("__NV_PRIME_RENDER_OFFLOAD", got)

    def test_amd_and_intel_keep_the_system_egl(self):
        for icd_present in (True, False):
            if not icd_present:
                os.remove(self.icd)
            for name, (gpus, boot) in WITHOUT_NVIDIA.items():
                got, forced = self.apply(gpus, boot)
                self.assertEqual(got, {}, "%s, icd file %s" % (name, icd_present))
                self.assertFalse(forced, name)

    def test_the_pre_gate_rule_did_force_nvidia_on_amd(self):
        # Otherwise the test above would pass without testing anything.
        want = {}
        pre_gate(want, *WITHOUT_NVIDIA["amd"], self.icd)
        self.assertIn("__EGL_VENDOR_LIBRARY_FILENAMES", want)

    def test_nvidia_driver_without_a_drm_node_counts(self):
        os.makedirs(os.path.join(self.tmp, "nvproc", "0000:01:00.0"))
        N.NVIDIA_PROC_GPUS = os.path.join(self.tmp, "nvproc")
        got, forced = self.apply(*WITHOUT_NVIDIA["intel"])
        self.assertTrue(forced)
        self.assertEqual(got["__EGL_VENDOR_LIBRARY_FILENAMES"], self.icd)

    def test_a_value_the_caller_set_is_left_alone(self):
        mesa = "/usr/share/glvnd/egl_vendor.d/50_mesa.json"
        got, _ = self.apply(*WITH_NVIDIA["nvidia"], start={"__EGL_VENDOR_LIBRARY_FILENAMES": mesa})
        self.assertEqual(got["__EGL_VENDOR_LIBRARY_FILENAMES"], mesa)
        got, _ = self.apply(*WITHOUT_NVIDIA["amd"], start={"__GLX_VENDOR_LIBRARY_NAME": "nvidia"})
        self.assertEqual(got, {"__GLX_VENDOR_LIBRARY_NAME": "nvidia"})

    def test_launch_uses_the_gate(self):
        src = inspect.getsource(N.cmd_launch)
        self.assertIn("_apply_gl_vendor_env(env, gpus)", src)
        for k in KEYS:                           # no second, ungated copy of the rule
            self.assertNotIn('setdefault("%s"' % k, src, k)
            self.assertNotIn('env["%s"] =' % k, src, k)
        self.assertNotIn("NVIDIA_EGL_ICD", src)


if __name__ == "__main__":
    unittest.main()
