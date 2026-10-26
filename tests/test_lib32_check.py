#!/usr/bin/env python3
"""Tests for the 32-bit C library check in `neutron setup` and `neutron doctor` (2026-10-21, GitHub Neutron#29).

Wine cannot start without the 32-bit program loader: the reporter's VM had no 32-bit libraries, `wineboot` stopped
with "/lib/ld-linux.so.2: could not open", and setup still finished. Setup now stops on it (like a missing cabextract)
and doctor reports it, both with the install command for the distribution. Each test builds a fake root.

Run:  python3 tests/test_lib32_check.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


class Lib32Check(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="neutron-lib32-")
        os.makedirs(os.path.join(self.root, "etc"))
        os.makedirs(os.path.join(self.root, "lib"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def distro(self, text):
        with open(os.path.join(self.root, "etc", "os-release"), "w") as f:
            f.write(text)

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def test_present_is_fine(self):
        self.distro("ID=cachyos\nID_LIKE=arch\n")
        self.write("lib/ld-linux.so.2")
        self.assertIsNone(N.lib32_problem(self.root))

    def test_missing_on_arch_with_multilib(self):
        self.distro("ID=cachyos\nID_LIKE=arch\n")
        self.write("etc/pacman.conf", "[options]\n\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n")
        p = N.lib32_problem(self.root)
        self.assertIn("/lib/ld-linux.so.2", p)
        self.assertIn("so Wine cannot start", p)
        self.assertIn("`sudo pacman -S lib32-glibc`", p)

    def test_missing_on_arch_without_multilib(self):
        self.distro("ID=arch\n")
        self.write("etc/pacman.conf", "[options]\n#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n")
        self.assertIn("enable the [multilib] repository", N.lib32_problem(self.root))

    def test_fedora_and_atomic_fedora(self):
        self.distro('ID=fedora\n')
        self.assertIn("`sudo dnf install glibc.i686`", N.lib32_problem(self.root))
        self.write("run/ostree-booted")
        self.assertIn("`rpm-ostree install glibc.i686`", N.lib32_problem(self.root))

    def test_opensuse(self):
        self.distro('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n')
        self.assertIn("`sudo zypper install glibc-32bit`", N.lib32_problem(self.root))

    def test_ubuntu(self):
        self.distro("ID=ubuntu\nID_LIKE=debian\n")
        self.assertIn("libc6:i386", N.lib32_problem(self.root))

    def test_unknown_distribution(self):
        self.distro("ID=somethingelse\n")
        self.assertIn("32-bit glibc package", N.lib32_problem(self.root))

    def test_setup_stops_on_it(self):
        with mock.patch.object(N, "lib32_problem", return_value="the 32-bit C library is missing"):
            problems, _ = N._setup_checks()
        self.assertIn("the 32-bit C library is missing", problems)

    def test_doctor_reports_it(self):
        with mock.patch.object(N, "lib32_problem", return_value="the 32-bit C library is missing"):
            checks = N.doctor_checks(None)
        lib32 = [c for c in checks if c["name"] == "lib32"]
        self.assertEqual(lib32, [{"name": "lib32", "ok": False, "detail": "the 32-bit C library is missing"}])
        self.assertFalse(N.doctor_healthy(checks))


if __name__ == "__main__":
    unittest.main()
