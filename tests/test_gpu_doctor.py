#!/usr/bin/env python3
"""Tests for `neutron doctor`'s GPU checks (AMD support audit X3, 2026-10-15).

  * `gpu`: each GPU's vendor, kernel driver and Vulkan driver (every machine).
  * `amd-rocm-opencl`, `opencl-loader`: only on a machine whose GPUs are AMD's with no NVIDIA one.
    Premiere, After Effects and Media Encoder render on an AMD GPU only through AMD's ROCm OpenCL
    (Adobe refuses Mesa's Rusticl by vendor name), and Wine's OpenCL.dll needs libOpenCL.so.1.
  * `amd-gfx-override` (with --prefix): HSA_OVERRIDE_GFX_VERSION=10.3.0 for the RDNA2 chips ROCm
    does not list, from the prefix's neutron-env.conf or the caller's environment.
Every finding is a warning at most (ok stays True). Nothing here touches the real system: each test
builds a fake filesystem root (sysfs, ICD files, libraries) and points the checks at it.

Run:  python3 tests/test_gpu_doctor.py
"""
import contextlib
import functools
import importlib.machinery
import importlib.util
import io
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

ELF64 = b"\x7fELF\x02\x01\x01" + b"\0" * 57
ELF32 = b"\x7fELF\x01\x01\x01" + b"\0" * 57
PCI_IDS = """\
# fake pci.ids
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t1638  Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]
\t164e  Raphael
\t6798  Tahiti XT [Radeon HD 7970/8970 OEM / R9 280X]
\t731f  Navi 10 [Radeon RX 5600 OEM/5600 XT / 5700/5700 XT]
\t73df  Navi 22 [Radeon RX 6700/6700 XT/6750 XT / 6800M/6850M XT]
\t\t1002 0e3b  Radeon RX 6700 XT
\t744c  Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M]
10de  NVIDIA Corporation
\t2f04  GB205 [GeForce RTX 5070]
8086  Intel Corporation
\ta780  Raptor Lake-S GT1 [UHD Graphics 770]
"""
RX6750 = ("0x1002", "0x73df", 100301)       # gfx1031
RX7900 = ("0x1002", "0x744c", 110000)       # gfx1100
RX5700 = ("0x1002", "0x731f", 100100)       # gfx1010
RAPHAEL = ("0x1002", "0x164e", 100306)      # gfx1036 (Ryzen 7000/9000 iGPU)
CEZANNE = ("0x1002", "0x1638", 90012)       # gfx90c
RTX5070 = ("0x10de", "0x2f04", None)
UHD770 = ("0x8086", "0xa780", None)


class FakeRoot:
    """A fake filesystem root: /sys/class/drm, /sys/class/kfd, ICD files, libraries, /dev/kfd."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="neutron-gpuroot-")
        self.cards = 0
        self.nodes = 1                           # KFD node 0 is the CPU
        self.write("sys/class/kfd/kfd/topology/nodes/0/properties",
                   "cpu_cores_count 16\nsimd_count 0\ngfx_target_version 0\nvendor_id 0\n")
        self.write("usr/share/hwdata/pci.ids", PCI_IDS)

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, data, mode=None):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(data, bytes) else "w") as f:
            f.write(data)
        if mode is not None:
            os.chmod(p, mode)
        return p

    def gpu(self, ids, driver, pci=None, kfd=True):
        vendor, device, gfx = ids
        pci = pci or "0000:%02x:00.0" % (3 + self.cards * 9)
        dev = self.path("sys/devices/pci0000:00/" + pci)
        os.makedirs(dev)
        self.write(dev + "/vendor", vendor + "\n")
        self.write(dev + "/device", device + "\n")
        if driver:
            drv = self.path("sys/bus/pci/drivers/" + driver)
            os.makedirs(drv, exist_ok=True)
            os.symlink(drv, dev + "/driver")
        card = self.path("sys/class/drm/card%d" % self.cards)
        os.makedirs(card)
        os.symlink(dev, card + "/device")
        os.makedirs(card + "-DP-1")              # a connector, not a GPU
        self.cards += 1
        if gfx and kfd and driver == "amdgpu":
            dom, rest = pci.split(":", 1)
            bus, devfn = rest.split(":")
            d, fn = devfn.split(".")
            loc = (int(bus, 16) << 8) | (int(d, 16) << 3) | int(fn)
            self.write("sys/class/kfd/kfd/topology/nodes/%d/properties" % self.nodes,
                       "cpu_cores_count 0\nsimd_count 80\ngfx_target_version %d\nvendor_id %d\n"
                       "device_id %d\nlocation_id %d\ndomain %d\ndrm_render_minor %d\n"
                       % (gfx, int(vendor, 16), int(device, 16), loc, int(dom, 16), 127 + self.nodes))
            self.nodes += 1
        return self

    def lib(self, rel, data=ELF64):
        self.write(rel, data)
        return self

    def vulkan(self, json_name, library, lib_rel=None, d="usr/share/vulkan/icd.d"):
        self.write(d + "/" + json_name,
                   json.dumps({"file_format_version": "1.0.1", "ICD": {"library_path": library}}))
        if lib_rel:
            self.lib(lib_rel)
        return self

    def radv(self):
        return self.vulkan("radeon_icd.x86_64.json", "/usr/lib/libvulkan_radeon.so",
                           "usr/lib/libvulkan_radeon.so")

    def nvidia_vk(self):
        return self.vulkan("nvidia_icd.json", "libGLX_nvidia.so.0", "usr/lib/libGLX_nvidia.so.0")

    def vk_loader(self):
        return self.lib("usr/lib/libvulkan.so.1")

    def ocl_loader(self, rel="usr/lib/libOpenCL.so.1", data=ELF64):
        return self.lib(rel, data)

    def rocm(self):
        """Arch's rocm-opencl-runtime: the ICD names a bare library that ld.so.conf.d/rocm.conf finds."""
        self.write("etc/OpenCL/vendors/amdocl64.icd", "libamdocl64.so\n")
        self.lib("opt/rocm/lib/libamdocl64.so")
        self.write("etc/ld.so.conf", "include /etc/ld.so.conf.d/*.conf\n")
        self.write("etc/ld.so.conf.d/rocm.conf", "/opt/rocm/lib\n")
        return self

    def rusticl(self):
        self.write("etc/OpenCL/vendors/rusticl.icd", "libRusticlOpenCL.so.1\n")
        return self.lib("usr/lib/libRusticlOpenCL.so.1")

    def kfd_dev(self, mode=0o666):
        self.write("dev/kfd", "", mode)
        return self

    def amd_desktop(self, ids=RX6750, rocm=True):
        """An AMD machine set up the way the one proven AMD tester's is (RADV, ROCm, both loaders)."""
        self.gpu(ids, "amdgpu").radv().vk_loader().ocl_loader().kfd_dev()
        return self.rocm() if rocm else self

    def cleanup(self):
        shutil.rmtree(self.root)


class Base(unittest.TestCase):
    def setUp(self):
        self.r = FakeRoot()
        self.tmp = tempfile.mkdtemp(prefix="neutron-gpuprefix-")

    def tearDown(self):
        self.r.cleanup()
        shutil.rmtree(self.tmp)

    def checks(self, env=None):
        gpus = N.host_gpus(self.r.root)
        return {c["name"]: c for c in N.gpu_checks(gpus, self.r.root, env={} if env is None else env)}

    def prefix(self, conf=None, name="Adobe"):
        p = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(p, "drive_c"), exist_ok=True)
        if conf is not None:
            with open(os.path.join(p, "neutron-env.conf"), "w") as f:
                f.write(conf)
        return p

    def override(self, conf=None, env=None, prefix=None):
        return N.gfx_override_check(N.host_gpus(self.r.root), prefix or self.prefix(conf), env=env or {})

    def assertWarning(self, c, *needles):
        self.assertTrue(c["ok"])
        self.assertTrue(c.get("warning"), c)
        for n in needles:
            self.assertIn(n, c["detail"])

    def assertClean(self, c):
        self.assertTrue(c["ok"])
        self.assertFalse(c.get("warning"), c)


class Helpers(unittest.TestCase):
    def test_gfx_names(self):
        for ver, name in ((100301, "gfx1031"), (100300, "gfx1030"), (90010, "gfx90a"), (90012, "gfx90c"),
                          (110000, "gfx1100"), (110003, "gfx1103"), (110501, "gfx1151"),
                          (120001, "gfx1201"), (80003, "gfx803"), (100100, "gfx1010")):
            self.assertEqual(N._gfx_name(ver), name)

    def test_rocm_support(self):
        s = N.rocm_gfx_support
        for v in (100300, 110000, 110001, 110002, 110003, 110500, 110501, 110502, 110503, 120000, 120001):
            self.assertEqual(s(v), "supported", N._gfx_name(v))
        for v in (100301, 100302, 100303, 100304, 100305, 100306, 100307):
            self.assertEqual(s(v), "override", N._gfx_name(v))
        for v in (100100, 100101, 100102, 90000, 90006, 90012, 80003, 70000):
            self.assertEqual(s(v), "none", N._gfx_name(v))
        for v in (90008, 90010, 90402, 90500, 120500, 0, None):
            self.assertEqual(s(v), "unknown", v)

    def test_pci_location(self):
        self.assertEqual(N._pci_slot_location("0000:03:00.0"), (0, 768))
        self.assertEqual(N._pci_slot_location("0001:0c:00.1"), (1, (0x0c << 8) | 1))
        self.assertIsNone(N._pci_slot_location("card0"))


class Inventory(Base):
    def test_this_machine_reads_without_error(self):
        # whatever this box is, the real sysfs must read and produce a `gpu` check
        gpus = N.host_gpus()
        names = [c["name"] for c in N.gpu_checks(gpus)]
        self.assertEqual(names[0], "gpu")

    def test_kfd_gfx_is_matched_by_pci_address(self):
        self.r.gpu(RAPHAEL, "amdgpu", pci="0000:0c:00.0").gpu(RX7900, "amdgpu", pci="0000:03:00.0")
        by_pci = {g["pci"]: g["gfx"] for g in N.host_gpus(self.r.root)}
        self.assertEqual(by_pci, {"0000:0c:00.0": "gfx1036", "0000:03:00.0": "gfx1100"})

    def test_names_from_pci_ids(self):
        self.r.gpu(RX6750, "amdgpu")
        g, = N.host_gpus(self.r.root)
        self.assertEqual(g["name"], "Radeon RX 6700/6700 XT/6750 XT / 6800M/6850M XT")
        self.assertEqual((g["vendor"], g["driver"], g["gfx"]), ("AMD", "amdgpu", "gfx1031"))

    def test_nvidia_without_a_drm_node_is_listed(self):
        self.r.gpu(UHD770, "i915")
        os.makedirs(self.r.path("proc/driver/nvidia/gpus/0000:01:00.0"))
        gpus = N.host_gpus(self.r.root)
        self.assertEqual([g["vendor"] for g in gpus], ["Intel", "NVIDIA"])

    def test_a_32_bit_library_does_not_count(self):
        self.r.lib("usr/lib/libOpenCL.so.1", ELF32)          # Fedora: /usr/lib is the 32-bit tree
        self.assertIsNone(N.find_shared_lib("libOpenCL.so.1", self.r.root))
        self.r.lib("usr/lib64/libOpenCL.so.1")
        self.assertTrue(N.find_shared_lib("libOpenCL.so.1", self.r.root).endswith("usr/lib64/libOpenCL.so.1"))

    def test_debian_multiarch_and_ld_so_conf(self):
        self.r.lib("usr/lib/x86_64-linux-gnu/libOpenCL.so.1")
        self.assertIsNotNone(N.find_shared_lib("libOpenCL.so.1", self.r.root))
        self.assertIsNone(N.find_shared_lib("libamdocl64.so", self.r.root))
        self.r.rocm()
        self.assertTrue(N.find_shared_lib("libamdocl64.so", self.r.root).endswith("opt/rocm/lib/libamdocl64.so"))

    def test_a_vulkan_icd_whose_library_is_gone_does_not_count(self):
        self.r.vulkan("radeon_icd.x86_64.json", "/usr/lib/libvulkan_radeon.so")     # no library
        self.assertEqual(N.vulkan_drivers(self.r.root, {}), {})
        self.r.lib("usr/lib/libvulkan_radeon.so")
        self.assertEqual(N.vulkan_drivers(self.r.root, {}), {"0x1002": ["RADV"]})


class NvidiaMachine(Base):
    def test_rtx_5070(self):
        self.r.gpu(RTX5070, "nvidia").nvidia_vk().vk_loader()
        c = self.checks()
        self.assertEqual(list(c), ["gpu"])                    # no AMD lines on an NVIDIA machine
        self.assertClean(c["gpu"])
        self.assertEqual(c["gpu"]["detail"], "NVIDIA GeForce RTX 5070 (10de:2f04) on nvidia, Vulkan: NVIDIA")
        self.assertIsNone(self.override("HSA_OVERRIDE_GFX_VERSION=10.3.0\n"))

    def test_amd_apu_laptop_with_nvidia(self):
        # Premiere uses CUDA on the NVIDIA GPU there: the ROCm checks do not apply
        self.r.gpu(RAPHAEL, "amdgpu").gpu(RTX5070, "nvidia").radv().nvidia_vk().vk_loader()
        self.assertEqual(list(self.checks()), ["gpu"])
        self.assertIsNone(self.override())

    def test_nvidia_vulkan_driver_missing(self):
        self.r.gpu(RTX5070, "nvidia").vk_loader()
        self.assertWarning(self.checks()["gpu"], "no Vulkan driver for the NVIDIA GPU", "nvidia-utils")

    def test_nouveau_is_not_served_by_nvidias_vulkan_driver(self):
        self.r.gpu(RTX5070, "nouveau").nvidia_vk().vk_loader()
        self.assertWarning(self.checks()["gpu"], "Vulkan: none")


class AmdMachine(Base):
    def test_rx6750xt_set_up_like_the_tester(self):
        self.r.amd_desktop()
        c = self.checks()
        self.assertEqual(list(c), ["gpu", "amd-rocm-opencl", "opencl-loader"])
        for v in c.values():
            self.assertClean(v)
        self.assertEqual(c["gpu"]["detail"], "AMD Radeon RX 6700/6700 XT/6750 XT / 6800M/6850M XT "
                                             "(1002:73df) on amdgpu, gfx1031, Vulkan: RADV")
        self.assertEqual(c["amd-rocm-opencl"]["detail"],
                         "AMD's ROCm OpenCL: /etc/OpenCL/vendors/amdocl64.icd (/opt/rocm/lib/libamdocl64.so)")
        self.assertEqual(c["opencl-loader"]["detail"], "/usr/lib/libOpenCL.so.1")
        self.assertEqual(c["gpu"]["gpus"][0]["gfx"], "gfx1031")

    def test_without_rocm(self):
        self.r.amd_desktop(rocm=False).rusticl()
        self.assertWarning(self.checks()["amd-rocm-opencl"], "not installed", "render on the CPU",
                           "Mesa's Rusticl", "rocm-opencl-runtime (Arch, CachyOS)", "rocm-opencl (Fedora",
                           "rocm-opencl-icd (Ubuntu")

    def test_rocm_icd_without_its_library(self):
        self.r.amd_desktop(rocm=False)
        self.r.write("etc/OpenCL/vendors/amdocl64.icd", "libamdocl64.so\n")
        self.assertWarning(self.checks()["amd-rocm-opencl"], "/etc/OpenCL/vendors/amdocl64.icd names "
                                                             "libamdocl64.so, which is not installed")

    @unittest.skipIf(os.geteuid() == 0, "root can open any file")
    def test_kfd_not_accessible(self):
        self.r.amd_desktop()
        os.chmod(self.r.path("dev/kfd"), 0)
        self.assertWarning(self.checks()["amd-rocm-opencl"], "cannot open /dev/kfd",
                           "sudo usermod -a -G render,video $LOGNAME")

    def test_no_opencl_loader(self):
        self.r.gpu(RX6750, "amdgpu").radv().vk_loader().rocm().kfd_dev()
        self.assertWarning(self.checks()["opencl-loader"], "libOpenCL.so.1 is missing",
                           "ocl-icd-libopencl1 (Debian, Ubuntu)")

    def test_no_vulkan_driver(self):
        self.r.gpu(RX6750, "amdgpu").vk_loader().ocl_loader().rocm().kfd_dev()
        self.assertWarning(self.checks()["gpu"], "no Vulkan driver for the AMD GPU", "vulkan-radeon (Arch)")

    def test_no_vulkan_loader(self):
        self.r.gpu(RX6750, "amdgpu").radv().ocl_loader().rocm().kfd_dev()
        self.assertWarning(self.checks()["gpu"], "libvulkan.so.1 is missing", "vulkan-icd-loader (Arch)")

    def test_rx5700xt_has_no_rocm(self):
        self.r.amd_desktop(ids=RX5700)
        self.assertWarning(self.checks()["amd-rocm-opencl"], "AMD's ROCm does not support", "gfx1010",
                           "render on the CPU")

    def test_old_radeon_driver(self):
        self.r.gpu(("0x1002", "0x6798", None), "radeon").radv().vk_loader().ocl_loader()
        c = self.checks()
        self.assertWarning(c["gpu"], "old radeon kernel driver, which has no Vulkan driver")
        self.assertWarning(c["amd-rocm-opencl"], "old radeon kernel driver, which ROCm does not support")

    def test_no_kfd_node(self):
        self.r.gpu(RX6750, "amdgpu", kfd=False).radv().vk_loader().ocl_loader().rocm()
        self.assertWarning(self.checks()["amd-rocm-opencl"], "no KFD node", "render on the CPU")

    def test_rx7900_with_the_ryzen_igpu(self):
        # ROCm runs the RX 7900 natively; the iGPU's gfx1036 must not drive an override suggestion,
        # because the override would apply to the RX 7900 too.
        self.r.amd_desktop(ids=RX7900).gpu(RAPHAEL, "amdgpu")
        c = self.checks()
        self.assertClean(c["amd-rocm-opencl"])
        self.assertIsNone(self.override())
        self.assertWarning(self.override("HSA_OVERRIDE_GFX_VERSION=10.3.0\n"), "applies to every AMD GPU",
                           "gfx1100", "remove it")


class GfxOverride(Base):
    def setUp(self):
        super().setUp()
        self.r.amd_desktop()                     # RX 6750 XT, gfx1031

    def test_set_in_the_prefix(self):
        p = self.prefix("HSA_OVERRIDE_GFX_VERSION=10.3.0\n")
        c = self.override(prefix=p)
        self.assertClean(c)
        self.assertIn(os.path.join(p, "neutron-env.conf"), c["detail"])
        self.assertIn("so ROCm treats", c["detail"])
        self.assertIn("(1002:73df, gfx1031) as gfx1030", c["detail"])

    def test_unset(self):
        p = self.prefix()
        self.assertWarning(self.override(prefix=p), "gfx1031", "not on ROCm's supported list",
                           "HSA_OVERRIDE_GFX_VERSION=10.3.0", os.path.join(p, "neutron-env.conf"))

    def test_set_in_this_environment_only(self):
        self.assertWarning(self.override(env={"HSA_OVERRIDE_GFX_VERSION": "10.3.0"}),
                           "this environment only", "app menu and Collider")

    def test_wrong_value(self):
        self.assertWarning(self.override("HSA_OVERRIDE_GFX_VERSION=11.0.0\n"), "=11.0.0",
                           "not the RDNA2 setting")

    def test_each_prefix_answers_for_itself(self):
        a = self.prefix("HSA_OVERRIDE_GFX_VERSION=10.3.0\n", name="A")
        b = self.prefix(name="B")
        self.assertClean(self.override(prefix=a))
        self.assertWarning(self.override(prefix=b), os.path.join(b, "neutron-env.conf"))

    def test_mixed_generations_get_no_suggestion(self):
        self.r.gpu(CEZANNE, "amdgpu")
        self.assertWarning(self.override(), "would also apply to", "gfx90c", "not been tested")


class NoRocmOverride(Base):
    def test_override_on_an_unsupported_card(self):
        self.r.amd_desktop(ids=RX5700)
        self.assertIsNone(self.override())
        self.assertWarning(self.override("HSA_OVERRIDE_GFX_VERSION=10.3.0\n"), "does not support",
                           "gfx1010", "not been tested")

    def test_supported_card_needs_nothing(self):
        self.r.amd_desktop(ids=RX7900)
        self.assertIsNone(self.override())


class DoctorOutput(Base):
    """The checks inside `neutron doctor --json`: present, warnings only, schema keys only."""

    def doctor(self, prefix):
        saved = (N.host_gpus, N.gpu_checks, N.resolve_wine)
        N.host_gpus = functools.partial(saved[0], root=self.r.root)
        N.gpu_checks = functools.partial(saved[1], root=self.r.root, env={})
        N.resolve_wine = lambda: (None, False)   # leave this machine's runtime out of it
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                N.main(["--json", "doctor", "--prefix", prefix])
        finally:
            N.host_gpus, N.gpu_checks, N.resolve_wine = saved
        return json.loads(out.getvalue())

    def test_amd_without_rocm_or_override(self):
        self.r.amd_desktop(rocm=False)
        p = self.prefix()
        saved = os.environ.pop("HSA_OVERRIDE_GFX_VERSION", None)
        try:
            d = self.doctor(p)
        finally:
            if saved is not None:
                os.environ["HSA_OVERRIDE_GFX_VERSION"] = saved
        c = {x["name"]: x for x in d["checks"]}
        for name in ("gpu", "amd-rocm-opencl", "opencl-loader", "amd-gfx-override"):
            self.assertIn(name, c)
            self.assertTrue(c[name]["ok"], name)
        self.assertTrue(c["amd-rocm-opencl"]["warning"])
        self.assertTrue(c["amd-gfx-override"]["warning"])
        allowed = {"name", "ok", "detail", "warning", "pending", "gpus"}
        for x in d["checks"]:
            if x["name"] in ("gpu", "amd-rocm-opencl", "opencl-loader", "amd-gfx-override"):
                self.assertLessEqual(set(x), allowed, x["name"])
        names = [x["name"] for x in d["checks"]]
        self.assertLess(names.index("gpu"), names.index("prefix"))       # machine checks come first
        self.assertGreater(names.index("amd-gfx-override"), names.index("prefix"))

    def test_nvidia(self):
        self.r.gpu(RTX5070, "nvidia").nvidia_vk().vk_loader()
        names = [x["name"] for x in self.doctor(self.prefix("HSA_OVERRIDE_GFX_VERSION=10.3.0\n"))["checks"]]
        self.assertIn("gpu", names)
        self.assertFalse([n for n in names if n.startswith("amd-") or n == "opencl-loader"], names)

    def test_a_crash_in_the_gpu_checks_does_not_take_doctor_down(self):
        saved = (N.host_gpus, N.resolve_wine)
        N.host_gpus = lambda *a, **k: 1 / 0
        N.resolve_wine = lambda: (None, False)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                N.main(["--json", "doctor", "--prefix", self.prefix()])
        finally:
            N.host_gpus, N.resolve_wine = saved
        c = {x["name"]: x for x in json.loads(out.getvalue())["checks"]}
        self.assertTrue(c["gpu"]["ok"])
        self.assertTrue(c["gpu"]["warning"])
        self.assertIn("prefix", c)


if __name__ == "__main__":
    unittest.main()
