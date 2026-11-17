#!/usr/bin/env python3
"""Setup installs the 32-bit libraries Wine's 32-bit side needs, not only the 32-bit C library (2026-11-17, Mud-Hut#3).

On Linux Mint 22.3 setup installed only libc6:i386. Every 32-bit program then ran without a display driver
("winewayland.so: libwayland-client.so.0: cannot open"): at provision both Visual C++ installers exited 130 ("Failed to
create window"), and a 32-bit window came up as a 6x32 sliver with no text (no FreeType). With the Wayland, font and
GnuTLS libraries added, both installers exit 0 and the 32-bit window is laid out (Mint 22.3 container, 2 of 2).
The plan now names each missing 32-bit library's package, and doctor/setup report what is missing. Each test builds a
fake root; a library counts only when the file there is 32-bit (Arch keeps 64-bit libraries in /usr/lib).

Run:  python3 tests/test_lib32_libs.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")
_spec = importlib.util.spec_from_loader("neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N)

ELF32 = b"\x7fELF\x01\x01\x01" + b"\0" * 9
ELF64 = b"\x7fELF\x02\x01\x01" + b"\0" * 9
MINT_SET = ("libwayland-client0:i386 libwayland-egl1:i386 libxkbcommon0:i386 libxkbregistry0:i386 libfreetype6:i386 "
            "libfontconfig1:i386 libgnutls30t64:i386 libx11-6:i386 libxext6:i386 libxcb1:i386 libxcb-randr0:i386 "
            "libxrender1:i386 libxrandr2:i386 libxi6:i386 libxcursor1:i386 libxfixes3:i386")


class Died(Exception):
    pass


class Lib32Libs(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="neutron-lib32libs-")
        os.makedirs(os.path.join(self.root, "etc"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def distro(self, text):
        with open(os.path.join(self.root, "etc", "os-release"), "w") as f:
            f.write(text)

    def put(self, rel, data=ELF32):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def loader(self):
        self.put("lib/ld-linux.so.2")

    def all_libs(self, d="usr/lib/i386-linux-gnu", data=ELF32, skip=()):
        for name, _why, _pk in N.LIB32_LIBS:
            if name not in skip:
                self.put(os.path.join(d, name), data)

    def plan(self):
        with mock.patch.object(N, "have", return_value=True):          # cabextract is there
            return N.prereq_plan(self.root)

    # -- what Mud-Hut#3's reporter had: the C library and nothing else --
    def test_mint_with_only_libc6_i386_gets_the_whole_set(self):
        self.distro("ID=linuxmint\nID_LIKE=\"ubuntu debian\"\n")
        self.loader()
        p = self.plan()
        self.assertTrue(p["can_install"])
        self.assertEqual(p["missing"], ["the 32-bit libraries for windows and text"])
        self.assertEqual(p["command"], "dpkg --add-architecture i386 && apt-get update; apt-get install -y " + MINT_SET)
        msg = N.lib32_problem(self.root)
        self.assertTrue(msg.startswith("the 32-bit libraries for windows, text and secure connections are missing"))
        self.assertIn("libwayland-client.so.0", msg)
        self.assertIn("`sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install " + MINT_SET + "`", msg)

    def test_a_fresh_ubuntu_gets_the_c_library_and_the_set_in_one_command(self):
        self.distro("ID=ubuntu\nID_LIKE=debian\n")
        p = self.plan()
        self.assertEqual(p["missing"], ["the 32-bit C library", "the 32-bit libraries for windows and text"])
        self.assertEqual(p["command"], "dpkg --add-architecture i386 && apt-get update; apt-get install -y libc6:i386 "
                         + MINT_SET)
        self.assertIn("so Wine cannot start", N.lib32_problem(self.root))         # the loader is still said first

    def test_everything_there_is_fine(self):
        self.distro("ID=linuxmint\nID_LIKE=\"ubuntu debian\"\n")
        self.loader()
        self.all_libs()
        self.assertIsNone(N.lib32_problem(self.root))
        self.assertEqual(self.plan()["missing"], [])

    def test_one_missing_library_names_only_its_package(self):
        self.distro("ID=ubuntu\nID_LIKE=debian\n")
        self.loader()
        self.all_libs(skip=("libfreetype.so.6",))
        self.assertEqual(self.plan()["command"],
                         "dpkg --add-architecture i386 && apt-get update; apt-get install -y libfreetype6:i386")
        msg = N.lib32_problem(self.root)
        self.assertIn("the 32-bit libraries for text are missing (libfreetype.so.6)", msg)

    def test_a_versioned_symlink_counts(self):
        self.distro("ID=ubuntu\nID_LIKE=debian\n")
        self.loader()
        self.all_libs(skip=("libfreetype.so.6",))
        self.put("usr/lib/i386-linux-gnu/libfreetype.so.6.20.1")
        os.symlink("libfreetype.so.6.20.1", os.path.join(self.root, "usr/lib/i386-linux-gnu/libfreetype.so.6"))
        self.assertIsNone(N.lib32_problem(self.root))

    def test_arch_64_bit_libraries_in_usr_lib_do_not_count(self):
        self.distro("ID=cachyos\nID_LIKE=arch\n")
        self.put("etc/pacman.conf", b"[core]\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n")
        self.loader()
        self.all_libs("usr/lib", ELF64)
        self.assertEqual(self.plan()["command"],
                         "pacman -S --needed --noconfirm lib32-wayland lib32-libxkbcommon lib32-freetype2 "
                         "lib32-fontconfig lib32-gnutls lib32-libx11 lib32-libxext lib32-libxcb lib32-libxrender "
                         "lib32-libxrandr lib32-libxi lib32-libxcursor lib32-libxfixes")
        self.all_libs("usr/lib32")
        self.assertIsNone(N.lib32_problem(self.root))

    def test_arch_without_multilib_gets_the_sentence(self):
        self.distro("ID=arch\n")
        self.put("etc/pacman.conf", b"[core]\n#[multilib]\n")
        self.loader()
        p = self.plan()
        self.assertFalse(p["can_install"])
        self.assertIn("enable the [multilib] repository", p["how"])
        self.assertIn("lib32-wayland", p["how"])

    def test_fedora_and_opensuse_install_by_library_name(self):
        self.distro("ID=fedora\n")
        names = " ".join(e[0] for e in N.LIB32_LIBS)
        self.assertEqual(self.plan()["command"], "dnf install -y glibc.i686 " + names)
        self.loader()
        self.assertEqual(self.plan()["command"], "dnf install -y " + names)
        self.put("run/ostree-booted")
        self.assertIn("rpm-ostree install " + names, self.plan()["how"])
        os.remove(os.path.join(self.root, "run/ostree-booted"))
        self.distro('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n')
        self.assertEqual(self.plan()["command"], "zypper --non-interactive install " + names)
        self.all_libs("usr/lib")                     # Fedora/openSUSE keep 32-bit libraries in /usr/lib
        self.assertIsNone(N.lib32_problem(self.root))

    def test_doctor_reports_the_missing_libraries(self):
        self.distro("ID=linuxmint\nID_LIKE=\"ubuntu debian\"\n")
        self.loader()
        real = N.lib32_problem
        with mock.patch.object(N, "lib32_problem", side_effect=lambda root="/": real(self.root)):
            checks = N.doctor_checks(None)
        lib32 = [c for c in checks if c["name"] == "lib32"][0]
        self.assertFalse(lib32["ok"])
        self.assertIn("cannot open windows or show text", lib32["detail"])
        self.assertFalse(N.doctor_healthy(checks))

    def test_setup_installs_them_like_the_c_library(self):
        problem = "the 32-bit libraries for windows and text are missing (libwayland-client.so.0)"
        plan = {"missing": ["the 32-bit libraries for windows and text"], "packages": ["libwayland-client0:i386"],
                "command": "apt-get update; apt-get install -y libwayland-client0:i386", "can_install": True, "how": None}
        args = SimpleNamespace(json=True, install_prereqs=True, yes=False, from_dir=None, no_ntsync=True)
        with mock.patch.object(N, "_setup_checks", side_effect=[([problem], []), ([], [])]), \
             mock.patch.object(N, "prereq_plan", return_value=plan), \
             mock.patch.object(N, "install_prereqs", return_value=True) as inst, \
             mock.patch.object(N, "die", side_effect=Died), \
             mock.patch.object(N, "event"), \
             mock.patch.object(N, "_installed", side_effect=Died):
            with self.assertRaises(Died):
                N.cmd_setup(args)
        inst.assert_called_once()


if __name__ == "__main__":
    unittest.main()
