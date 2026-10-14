#!/usr/bin/env python3
"""Tests for hybrid-GPU detection (NVIDIA next to an Intel/AMD iGPU).

GitHub Neutron#12 (2026-10-13): on an Intel + RTX 4050 laptop, Wine's EGL got no configs ("Failed to get
any configs from eglChooseConfig") because the launcher forces NVIDIA's EGL vendor but never asked for
PRIME render offload; Premiere's CUDA renderer then never delivered a frame. `launch` sets
__NV_PRIME_RENDER_OFFLOAD=1 only when `nvidia_render_offload(drm_gpus(), boot_gpu_vendor())` is true: a
hybrid machine whose desktop runs on the other GPU. NVIDIA-only machines, and desktops that boot on
NVIDIA with an iGPU also enabled, keep the environment they were tested with.

Run:  python3 tests/test_hybrid_gpu.py
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


class DrmTree:
    """A fake /sys/class/drm: cardN -> device/{vendor,driver}."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="neutron-drm-")
        self.drivers = os.path.join(self.root, "_drivers")
        os.makedirs(self.drivers)

    def card(self, name, vendor=None, driver=None, boot_vga=None):
        dev = os.path.join(self.root, "_devices", name)
        os.makedirs(dev)
        if vendor:
            with open(os.path.join(dev, "vendor"), "w") as f:
                f.write(vendor + "\n")
        if boot_vga is not None:
            with open(os.path.join(dev, "boot_vga"), "w") as f:
                f.write("%d\n" % boot_vga)
        if driver:
            os.makedirs(os.path.join(self.drivers, driver), exist_ok=True)
            os.symlink(os.path.join(self.drivers, driver), os.path.join(dev, "driver"))
        os.makedirs(os.path.join(self.root, name))
        os.symlink(dev, os.path.join(self.root, name, "device"))
        return self

    def cleanup(self):
        shutil.rmtree(self.root)


class HybridGpu(unittest.TestCase):
    def setUp(self):
        self.t = DrmTree()

    def tearDown(self):
        self.t.cleanup()

    def test_intel_plus_nvidia_laptop_is_hybrid(self):
        self.t.card("card0", "0x8086", "i915").card("card1", "0x10de", "nvidia")
        self.t.card("card1-HDMI-A-1")  # a connector, not a GPU
        gpus = N.drm_gpus(self.t.root)
        self.assertEqual(gpus, [("0x8086", "i915"), ("0x10de", "nvidia")])
        self.assertTrue(N.nvidia_hybrid(gpus))

    def test_amd_plus_nvidia_is_hybrid(self):
        self.t.card("card0", "0x1002", "amdgpu").card("card1", "0x10de", "nvidia")
        self.assertTrue(N.nvidia_hybrid(N.drm_gpus(self.t.root)))

    def test_nvidia_only_desktop_is_not_hybrid(self):
        self.t.card("card1", "0x10de", "nvidia").card("card1-DP-1")
        self.t.card("card0")  # simpledrm: no PCI vendor
        gpus = N.drm_gpus(self.t.root)
        self.assertEqual(gpus, [("0x10de", "nvidia")])
        self.assertFalse(N.nvidia_hybrid(gpus))

    def test_two_nvidia_gpus_are_not_hybrid(self):
        self.t.card("card0", "0x10de", "nvidia").card("card1", "0x10de", "nvidia")
        self.assertFalse(N.nvidia_hybrid(N.drm_gpus(self.t.root)))

    def test_amd_only_is_not_hybrid(self):
        self.t.card("card0", "0x1002", "amdgpu")
        self.assertFalse(N.nvidia_hybrid(N.drm_gpus(self.t.root)))

    def test_no_drm_at_all(self):
        self.assertEqual(N.drm_gpus(os.path.join(self.t.root, "missing")), [])
        self.assertFalse(N.nvidia_hybrid([]))
        self.assertIsNone(N.boot_gpu_vendor(os.path.join(self.t.root, "missing")))


class RenderOffload(unittest.TestCase):
    """PRIME render offload only when the desktop runs on the OTHER GPU (the boot GPU, which KWin and
    Mutter render on by default)."""

    def setUp(self):
        self.t = DrmTree()

    def tearDown(self):
        self.t.cleanup()

    def offload(self):
        return N.nvidia_render_offload(N.drm_gpus(self.t.root), N.boot_gpu_vendor(self.t.root))

    def test_laptop_booting_on_the_igpu_offloads(self):
        self.t.card("card0", "0x8086", "i915", boot_vga=1).card("card1", "0x10de", "nvidia", boot_vga=0)
        self.assertEqual(N.boot_gpu_vendor(self.t.root), "0x8086")
        self.assertTrue(self.offload())

    def test_amd_apu_laptop_offloads(self):
        self.t.card("card0", "0x10de", "nvidia", boot_vga=0).card("card1", "0x1002", "amdgpu", boot_vga=1)
        self.assertTrue(self.offload())

    def test_desktop_booting_on_nvidia_with_igpu_enabled_does_not(self):
        self.t.card("card0", "0x8086", "i915", boot_vga=0).card("card1", "0x10de", "nvidia", boot_vga=1)
        self.assertTrue(N.nvidia_hybrid(N.drm_gpus(self.t.root)))
        self.assertFalse(self.offload())

    def test_hybrid_without_boot_vga_is_treated_as_a_laptop(self):
        self.t.card("card0", "0x8086", "i915").card("card1", "0x10de", "nvidia")
        self.assertIsNone(N.boot_gpu_vendor(self.t.root))
        self.assertTrue(self.offload())

    def test_nvidia_only_never_offloads(self):
        self.t.card("card1", "0x10de", "nvidia", boot_vga=1).card("card1-DP-1")
        self.assertFalse(self.offload())

    def test_amd_only_never_offloads(self):
        self.t.card("card0", "0x1002", "amdgpu", boot_vga=1)
        self.assertFalse(self.offload())

    def test_this_machine_matches_its_own_sysfs(self):
        # whatever this box is, the decision must equal the rule applied to the real sysfs
        gpus, boot = N.drm_gpus(), N.boot_gpu_vendor()
        self.assertEqual(N.nvidia_render_offload(gpus, boot),
                         N.nvidia_hybrid(gpus) and boot != N.NVIDIA_PCI_VENDOR)


if __name__ == "__main__":
    unittest.main()
