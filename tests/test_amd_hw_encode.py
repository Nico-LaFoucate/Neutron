#!/usr/bin/env python3
"""Tests for `neutron doctor`'s `amd-hw-encode` check (AMD hardware encoding, 2026-10-16).

Our amfrt64.dll (runtime 11.10-128 and later) answers the AMF calls Premiere, Media Encoder and After
Effects make on an AMD GPU and encodes through Mesa. When one of those apps loads it, it writes what it
found to <prefix>/neutron-amf.json. Doctor reads that file only:
  * ok when H.264 is available (the detail lists the codecs, the backend and 10-bit);
  * a warning (ok stays True) with the reason and the one fix when it is not, the fix chosen from
    /etc/os-release: RPM Fusion's freeworld Mesa on Fedora, Packman's on openSUSE, a system update for
    old VCN firmware;
  * pending when nothing has been recorded yet;
  * a warning when Premiere's GPU acceleration (ROCm OpenCL) is not working, since Premiere offers
    Hardware Encoding only while it is on;
  * nothing at all on a machine with an NVIDIA GPU (NVENC there), or a prefix without amfrt64.dll.
Every test builds a fake filesystem root and a fake prefix; nothing is run.

Run:  python3 tests/test_amd_hw_encode.py
"""
import contextlib
import functools
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_gpu_doctor import FakeRoot, N, RX7900, RTX5070   # noqa: E402

FEDORA = 'NAME="Fedora Linux"\nVERSION_ID=44\nID=fedora\nVARIANT_ID=workstation\n'
KINOITE = 'NAME="Fedora Linux"\nVERSION_ID=44\nID=fedora\nVARIANT_ID=kinoite\n'
TUMBLEWEED = 'NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
CACHYOS = 'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n'
UBUNTU = 'NAME="Ubuntu"\nVERSION_ID="26.04"\nID=ubuntu\nID_LIKE=debian\n'

NO_H264_IN_MESA = "The Vulkan driver has no H.264 encoder (the distro may build Mesa without H.264)."
NO_HEVC_IN_MESA = "The Vulkan driver has no HEVC encoder (the distro may build Mesa without HEVC)."
OLD_FIRMWARE = ("The Vulkan driver for AMD Radeon RX 6700 XT (RADV NAVI22) does not offer video encoding "
                "(Mesa may be too old, or this GPU's firmware needs RADV_PERFTEST=video_encode).")

PREMIERE = "drive_c/Program Files/Adobe/Adobe Premiere Pro 2025/Adobe Premiere Pro.exe"
MEDIA_ENCODER = "drive_c/Program Files/Adobe/Adobe Media Encoder 2026/Adobe Media Encoder.exe"
PHOTOSHOP = "drive_c/Program Files/Adobe/Adobe Photoshop 2026/Photoshop.exe"


def codec(available, backend="vulkan", w=4096, h=2304, tenbit=False, reason=""):
    return {"available": available, "backend": backend if available else "none",
            "max_width": w if available else 0, "max_height": h if available else 0,
            "tenbit": tenbit, "reason": reason}


GOOD = {"h264": codec(True), "hevc": codec(True, w=8192, h=4352, tenbit=True)}
NO_CODECS = {"h264": codec(False, reason=NO_H264_IN_MESA), "hevc": codec(False, reason=NO_HEVC_IN_MESA)}


class Base(unittest.TestCase):
    def setUp(self):
        self.r = FakeRoot()
        self.tmp = tempfile.mkdtemp(prefix="neutron-amfprefix-")
        self.p = os.path.join(self.tmp, "Adobe")
        os.makedirs(os.path.join(self.p, "drive_c"))

    def tearDown(self):
        self.r.cleanup()
        shutil.rmtree(self.tmp)

    def touch(self, rel, data=b"MZ"):
        path = os.path.join(self.p, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return self

    def staged(self):                              # what runtime 11.10-128 stages
        return self.touch("drive_c/windows/system32/amfrt64.dll")

    def report(self, codecs, gpu_name="AMD Radeon RX 6700 XT (RADV NAVI22)", raw=None):
        with open(os.path.join(self.p, "neutron-amf.json"), "w") as f:
            if raw is not None:
                f.write(raw)
            else:
                json.dump({"format": 1, "time": "2026-10-16T09:12:33Z",
                           "gpu": {"vendor": "0x1002", "device": "0x73df", "name": gpu_name},
                           "codecs": codecs}, f)
        return self

    def distro(self, text):
        self.r.write("etc/os-release", text)
        return self

    def check(self, checks=()):
        return N.amd_hw_encode_check(N.host_gpus(self.r.root), self.p, list(checks), root=self.r.root)

    def gpu_checks(self):
        return N.gpu_checks(N.host_gpus(self.r.root), self.r.root, env={})

    def assertWarning(self, c, *needles):
        self.assertEqual(c["name"], "amd-hw-encode")
        self.assertTrue(c["ok"])
        self.assertTrue(c.get("warning"), c)
        for n in needles:
            self.assertIn(n, c["detail"])

    def assertClean(self, c):
        self.assertTrue(c["ok"])
        self.assertFalse(c.get("warning"), c)
        self.assertFalse(c.get("pending"), c)


class Applies(Base):
    def setUp(self):
        super().setUp()
        self.r.amd_desktop()

    def test_pending_before_the_first_start(self):
        self.staged().touch(PREMIERE)
        c = self.check()
        self.assertTrue(c["ok"])
        self.assertTrue(c["pending"])
        self.assertFalse(c.get("warning"))
        self.assertTrue(c["detail"].startswith("pending — start Premiere Pro, Media Encoder or After "
                                               "Effects once"), c["detail"])

    def test_media_encoder_alone_is_enough_for_pending(self):
        self.staged().touch(MEDIA_ENCODER)
        self.assertTrue(self.check()["pending"])

    def test_nothing_to_say_without_an_app_that_encodes(self):
        self.staged().touch(PHOTOSHOP)
        self.assertIsNone(self.check())

    def test_nothing_to_say_on_a_runtime_without_amfrt64(self):
        # 11.10-127 has no amfrt64.dll; an old report from 128 says nothing about this runtime
        self.touch(PREMIERE).report(NO_CODECS)
        self.assertIsNone(self.check())

    def test_an_unreadable_report_is_a_warning(self):
        self.staged().touch(PREMIERE).report(None, raw="{not json")
        self.assertWarning(self.check(), "could not read", "neutron-amf.json", "start Premiere Pro")
        self.report(None, raw=json.dumps({"format": 2, "codecs": {}}))
        self.assertWarning(self.check(), "not a format-1 report")


class Available(Base):
    def setUp(self):
        super().setUp()
        self.r.amd_desktop()
        self.staged().touch(PREMIERE)

    def test_h264_and_hevc(self):
        self.report(GOOD)
        c = self.check(self.gpu_checks())
        self.assertClean(c)
        self.assertEqual(c["detail"], "hardware encoding on AMD Radeon RX 6700 XT (RADV NAVI22): "
                                      "H.264 (Vulkan Video, 8-bit, up to 4096x2304), "
                                      "HEVC (Vulkan Video, 10-bit, up to 8192x4352)")

    def test_vaapi_backend(self):
        self.report({"h264": codec(True, backend="vaapi"), "hevc": codec(True, backend="vaapi")})
        self.assertIn("H.264 (VA-API, 8-bit", self.check()["detail"])

    def test_h264_without_hevc_is_still_ok(self):
        self.report({"h264": codec(True), "hevc": codec(False, reason="The Vulkan driver's HEVC encoder "
                                                                       "does not take NV12 frames.")})
        c = self.check()
        self.assertClean(c)
        self.assertIn("HEVC not available (The Vulkan driver's HEVC encoder does not take NV12 frames)",
                      c["detail"])

    def test_no_rocm_means_premiere_will_not_offer_it(self):
        self.r.cleanup()
        self.r = FakeRoot()
        self.r.amd_desktop(rocm=False)
        self.report(GOOD)
        c = self.check(self.gpu_checks())
        self.assertWarning(c, "H.264 (Vulkan Video", "Premiere offers Hardware Encoding only while its GPU "
                           "acceleration is on", "ROCm OpenCL", "fix the amd-rocm-opencl warning first")

    def test_a_missing_gfx_override_is_cited_too(self):
        self.report(GOOD)
        rocm = self.gpu_checks()
        ovr = N.gfx_override_check(N.host_gpus(self.r.root), self.p, env={})   # RX 6750 XT, unset
        self.assertWarning(self.check(rocm + [ovr]), "fix the amd-gfx-override warning first")


class NotAvailable(Base):
    def setUp(self):
        super().setUp()
        self.r.amd_desktop()
        self.staged().touch(PREMIERE)

    def test_fedora_without_rpm_fusion(self):
        self.distro(FEDORA).report(NO_CODECS)
        c = self.check(self.gpu_checks())
        self.assertWarning(
            c, "no H.264 hardware encoding on AMD Radeon RX 6700 XT (RADV NAVI22): " + NO_H264_IN_MESA[:-1],
            "This system's Mesa is built without H.264 and HEVC. Install RPM Fusion's full build: "
            "sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-"
            "$(rpm -E %fedora).noarch.rpm, then sudo dnf install mesa-va-drivers-freeworld, then "
            "sudo dnf swap mesa-vulkan-drivers mesa-vulkan-drivers-freeworld, then restart the app.",
            "Until then Premiere Pro, Media Encoder and After Effects export with Software Encoding "
            "(checked 2026-10-16 09:12 UTC; start one of them again after the fix to check again)")
        self.assertNotIn("ROCm", c["detail"])

    def test_fedora_with_rpm_fusion_enabled(self):
        self.distro(FEDORA).report(NO_CODECS)
        self.r.write("etc/yum.repos.d/rpmfusion-free.repo", "[rpmfusion-free]\n")
        c = self.check()
        self.assertWarning(c, "Install RPM Fusion's full build: sudo dnf install mesa-va-drivers-freeworld, "
                              "then sudo dnf swap mesa-vulkan-drivers mesa-vulkan-drivers-freeworld")
        self.assertNotIn("rpmfusion-free-release", c["detail"])

    def test_image_based_fedora_gets_no_dnf_command(self):
        self.distro(KINOITE).report(NO_CODECS)
        self.r.write("run/ostree-booted", "")
        c = self.check()
        self.assertWarning(c, "image-based Fedora", "mesa-va-drivers-freeworld",
                           "mesa-vulkan-drivers-freeworld")
        self.assertNotIn("dnf", c["detail"])

    def test_opensuse_without_opi(self):
        self.distro(TUMBLEWEED).report(NO_CODECS)
        self.assertWarning(self.check(), "Install Packman's full build: sudo zypper install opi, then "
                                         "opi codecs, then restart the app")

    def test_opensuse_with_opi(self):
        self.distro(TUMBLEWEED).report(NO_CODECS)
        self.r.write("usr/bin/opi", "#!/usr/bin/python3\n")
        c = self.check()
        self.assertWarning(c, "Install Packman's full build: opi codecs, then restart the app")
        self.assertNotIn("zypper install opi", c["detail"])

    def test_old_vcn_firmware_on_cachyos(self):
        self.distro(CACHYOS).report({"h264": codec(False, reason=OLD_FIRMWARE),
                                     "hevc": codec(False, reason=OLD_FIRMWARE)})
        c = self.check()
        self.assertWarning(c, "does not offer video encoding", "needs a newer linux-firmware and Mesa: "
                           "update your system (sudo pacman -Syu), then restart the computer")
        self.assertNotIn("freeworld", c["detail"])

    def test_old_vcn_firmware_on_ubuntu(self):
        self.distro(UBUNTU).report({"h264": codec(False, reason=OLD_FIRMWARE), "hevc": codec(False)})
        self.assertWarning(self.check(), "sudo apt update && sudo apt full-upgrade")

    def test_no_vulkan_loader(self):
        self.distro(CACHYOS).report({"h264": codec(False, reason="Vulkan is not installed (libvulkan.so.1 "
                                                                 "was not found)."), "hevc": codec(False)})
        self.assertWarning(self.check(), "Install the Vulkan loader: vulkan-icd-loader (Arch)")

    def test_an_unknown_reason_is_passed_on_without_a_made_up_fix(self):
        self.distro(FEDORA).report({"h264": codec(False, reason="Something new went wrong."),
                                    "hevc": codec(False)})
        c = self.check()
        self.assertWarning(c, "Something new went wrong. Until then Premiere Pro")
        self.assertNotIn("dnf", c["detail"])

    def test_the_codec_fix_on_an_unknown_distro(self):
        self.report(NO_CODECS)                                     # no os-release at all
        self.assertWarning(self.check(), "install your distribution's Mesa build that includes them")


class OtherMachines(Base):
    def test_nvidia_machine_says_nothing(self):
        self.r.gpu(RTX5070, "nvidia").nvidia_vk().vk_loader()
        self.staged().touch(PREMIERE).report(NO_CODECS)
        self.assertIsNone(self.check())
        self.report(GOOD)
        self.assertIsNone(self.check())

    def test_amd_igpu_with_nvidia_says_nothing(self):
        # Premiere encodes with NVENC on the NVIDIA GPU there
        self.r.amd_desktop(ids=RX7900).gpu(RTX5070, "nvidia").nvidia_vk()
        self.staged().touch(PREMIERE).report(NO_CODECS)
        self.assertIsNone(self.check())

    def test_no_gpu_listed_says_nothing(self):
        self.staged().touch(PREMIERE)
        self.assertIsNone(self.check())


class DoctorOutput(Base):
    """`neutron doctor --json --prefix`: the check is there, ok, and only uses the schema's keys."""

    def doctor(self):
        saved = (N.host_gpus, N.gpu_checks, N.resolve_wine, N.amd_hw_encode_check)
        N.host_gpus = functools.partial(saved[0], root=self.r.root)
        N.gpu_checks = functools.partial(saved[1], root=self.r.root, env={})
        N.resolve_wine = lambda: (None, False)
        N.amd_hw_encode_check = functools.partial(saved[3], root=self.r.root)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                N.main(["--json", "doctor", "--prefix", self.p])
        finally:
            N.host_gpus, N.gpu_checks, N.resolve_wine, N.amd_hw_encode_check = saved
        return {c["name"]: c for c in json.loads(out.getvalue())["checks"]}

    def test_warning_never_fails_doctor(self):
        self.r.amd_desktop()
        self.distro(FEDORA)
        self.staged().touch(PREMIERE).report(NO_CODECS)
        c = self.doctor()["amd-hw-encode"]
        self.assertTrue(c["ok"])
        self.assertTrue(c["warning"])
        self.assertLessEqual(set(c), {"name", "ok", "detail", "warning", "pending"})

    def test_pending_in_doctor(self):
        self.r.amd_desktop()
        self.staged().touch(PREMIERE)
        c = self.doctor()["amd-hw-encode"]
        self.assertEqual((c["ok"], c.get("pending")), (True, True))

    def test_absent_on_nvidia(self):
        self.r.gpu(RTX5070, "nvidia").nvidia_vk().vk_loader()
        self.staged().touch(PREMIERE).report(NO_CODECS)
        self.assertNotIn("amd-hw-encode", self.doctor())

    def test_a_crash_in_the_check_does_not_take_doctor_down(self):
        self.r.amd_desktop()
        self.staged().touch(PREMIERE)
        saved = N.os_release
        N.os_release = lambda *a, **k: 1 / 0
        try:
            self.report(NO_CODECS)
            c = self.doctor()["amd-hw-encode"]
        finally:
            N.os_release = saved
        self.assertTrue(c["ok"])
        self.assertTrue(c["warning"])
        self.assertIn("could not check AMD hardware encoding", c["detail"])


class OsRelease(unittest.TestCase):
    def test_families(self):
        fam = lambda text: N._distro_family(dict(  # noqa: E731
            (k, v.strip('"')) for k, _, v in (ln.partition("=") for ln in text.splitlines())))
        self.assertEqual(fam(FEDORA), "fedora")
        self.assertEqual(fam(TUMBLEWEED), "opensuse")
        self.assertEqual(fam('ID="opensuse-leap"\nID_LIKE="suse opensuse"'), "opensuse")
        self.assertEqual(fam(CACHYOS), "arch")
        self.assertEqual(fam(UBUNTU), "debian")
        self.assertEqual(fam('ID=bazzite\nID_LIKE="fedora"'), "fedora")
        self.assertEqual(fam('ID=pop\nID_LIKE="ubuntu debian"'), "debian")
        self.assertIsNone(fam("ID=gentoo"))

    def test_reads_usr_lib_when_etc_is_missing(self):
        r = FakeRoot()
        try:
            r.write("usr/lib/os-release", CACHYOS)
            self.assertEqual(N.os_release(r.root)["ID"], "cachyos")
            r.write("etc/os-release", 'ID="opensuse-tumbleweed"\n# comment\n')
            self.assertEqual(N.os_release(r.root), {"ID": "opensuse-tumbleweed"})
        finally:
            r.cleanup()


if __name__ == "__main__":
    unittest.main()
