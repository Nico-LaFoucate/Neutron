#!/usr/bin/env python3
"""Setup installs its own missing system packages (2026-10-27, his "get a non-terminal install working before MAX").

When the 32-bit C library or cabextract is missing, `neutron setup` works out the package command for the distribution.
In a terminal it asks and runs it with sudo; from Collider (`--json`) it stops with the plan, and Collider runs setup
again with `--install-prereqs`, which runs the command through pkexec (the desktop's password dialog). Image-based
systems and Arch without [multilib] get a sentence instead. Each distro test builds a fake root.

Run:  python3 tests/test_prereq_install.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")
_spec = importlib.util.spec_from_loader("neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N)


class Died(Exception):
    pass


class Plan(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="neutron-prereq-")
        os.makedirs(os.path.join(self.root, "etc"))
        os.makedirs(os.path.join(self.root, "lib"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def distro(self, text):
        with open(os.path.join(self.root, "etc", "os-release"), "w") as f:
            f.write(text)

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def plan(self, cabextract=False):
        with mock.patch.object(N, "have", side_effect=lambda b: cabextract if b == "cabextract" else True):
            return N.prereq_plan(self.root)

    def test_nothing_missing(self):
        self.distro("ID=fedora\n")
        self.write("lib/ld-linux.so.2")
        p = self.plan(cabextract=True)
        self.assertEqual(p["missing"], [])
        self.assertFalse(p["can_install"])

    def test_fedora(self):
        self.distro("ID=fedora\n")
        p = self.plan()
        self.assertEqual(p["command"], "dnf install -y glibc.i686 cabextract")
        self.assertTrue(p["can_install"])
        self.assertEqual(p["missing"], ["the 32-bit C library", "cabextract"])

    def test_fedora_atomic_needs_a_restart(self):
        self.distro("ID=fedora\nVARIANT_ID=kinoite\n")
        self.write("run/ostree-booted")
        p = self.plan()
        self.assertFalse(p["can_install"])
        self.assertIn("rpm-ostree install glibc.i686 cabextract", p["how"])
        self.assertIn("restart", p["how"])

    def test_ubuntu_adds_the_i386_architecture_only_for_the_32_bit_library(self):
        self.distro("ID=ubuntu\nID_LIKE=debian\n")
        p = self.plan()
        self.assertEqual(p["command"], "dpkg --add-architecture i386 && apt-get update && apt-get install -y libc6:i386 cabextract")
        self.write("lib/ld-linux.so.2")
        p = self.plan()
        self.assertEqual(p["command"], "apt-get update && apt-get install -y cabextract")

    def test_opensuse(self):
        self.distro('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n')
        self.assertEqual(self.plan()["command"], "zypper --non-interactive install glibc-32bit cabextract")

    def test_arch_with_and_without_multilib(self):
        self.distro("ID=cachyos\nID_LIKE=arch\n")
        self.write("etc/pacman.conf", "[core]\n#[multilib]\n")
        p = self.plan()
        self.assertFalse(p["can_install"])
        self.assertIn("[multilib]", p["how"])
        self.write("etc/pacman.conf", "[core]\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n")
        self.assertEqual(self.plan()["command"], "pacman -S --needed --noconfirm lib32-glibc cabextract")
        self.write("lib/ld-linux.so.2")
        self.assertEqual(self.plan()["command"], "pacman -S --needed --noconfirm cabextract")

    def test_unknown_distribution(self):
        self.distro("ID=nixos\n")
        p = self.plan()
        self.assertFalse(p["can_install"])
        self.assertIn("32-bit glibc", p["how"])


class Install(unittest.TestCase):
    PLAN = {"missing": ["cabextract"], "packages": ["cabextract"], "command": "dnf install -y cabextract",
            "can_install": True, "how": None}

    def test_collider_path_uses_pkexec_without_asking(self):
        with mock.patch.object(N.sys.stdin, "isatty", return_value=False), \
             mock.patch.object(N, "have", return_value=True), \
             mock.patch.object(N.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(N.install_prereqs(self.PLAN, as_json=True, assume_yes=False))
        self.assertEqual(run.call_args[0][0], ["pkexec", "sh", "-c", "dnf install -y cabextract"])

    def test_terminal_asks_then_uses_sudo(self):
        with mock.patch.object(N.sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch.object(N.subprocess, "run") as run:
            self.assertFalse(N.install_prereqs(self.PLAN, as_json=False, assume_yes=False))
        run.assert_not_called()
        with mock.patch.object(N.sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value="y"), \
             mock.patch.object(N.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(N.install_prereqs(self.PLAN, as_json=False, assume_yes=False))
        self.assertEqual(run.call_args[0][0][:3], ["sudo", "sh", "-c"])


class Setup(unittest.TestCase):
    PROBLEM = "cabextract is missing (it unpacks Microsoft's installers). Install it: ..."
    PLAN = Install.PLAN
    NTSYNC = None           # ntsync already on (or absent): the plan is the packages alone

    def run_setup(self, install_flag, checks, no_ntsync=False):
        args = SimpleNamespace(json=True, install_prereqs=install_flag, yes=False, from_dir=None, no_ntsync=no_ntsync)
        died = {}

        def fake_die(obj, code, as_json):
            died.update(obj)
            raise Died()
        with mock.patch.object(N, "_setup_checks", side_effect=checks), \
             mock.patch.object(N, "prereq_plan", return_value=self.PLAN), \
             mock.patch.object(N, "_ntsync_enable_cmd", return_value=self.NTSYNC), \
             mock.patch.object(N, "install_prereqs", return_value=True) as inst, \
             mock.patch.object(N, "die", side_effect=fake_die), \
             mock.patch.object(N, "event"), \
             mock.patch.object(N, "_installed", side_effect=Died):
            with self.assertRaises(Died):
                N.cmd_setup(args)
        return died, inst

    def test_collider_gets_the_plan_when_it_did_not_ask_to_install(self):
        died, inst = self.run_setup(False, [([self.PROBLEM], [])])
        inst.assert_not_called()
        self.assertEqual(died["prereqs"]["command"], "dnf install -y cabextract")

    def test_install_prereqs_installs_then_carries_on(self):
        died, inst = self.run_setup(True, [([self.PROBLEM], []), ([], [])])
        inst.assert_called_once()
        self.assertEqual(died, {})          # reached the setup steps (stopped by the test at _installed)

    def test_never_installs_when_something_else_stops_setup(self):
        died, inst = self.run_setup(True, [([self.PROBLEM, "glibc 2.35 is too old; Neutron needs 2.39"], [])])
        inst.assert_not_called()
        self.assertIn("prereqs", died)


class OnePassword(Setup):
    """2026-10-27, Ubuntu 26.04 VM: the system asked for the password twice, for the packages and then for
    ntsync. His "so they only need to enter their password once": one command does both."""
    NTSYNC = "echo ntsync > /etc/modules-load.d/ntsync.conf && modprobe ntsync"

    def test_collider_gets_the_plan_when_it_did_not_ask_to_install(self):
        died, _ = self.run_setup(False, [([self.PROBLEM], [])])
        self.assertEqual(died["prereqs"]["command"], "dnf install -y cabextract && { %s || true; }" % self.NTSYNC)
        self.assertIs(died["prereqs"]["ntsync"], True)

    def test_installs_both_with_one_command(self):
        _, inst = self.run_setup(True, [([self.PROBLEM], []), ([], [])])
        self.assertIn("modprobe ntsync", inst.call_args[0][0]["command"])

    def test_no_ntsync_keeps_the_packages_alone(self):
        died, _ = self.run_setup(False, [([self.PROBLEM], [])], no_ntsync=True)
        self.assertEqual(died["prereqs"]["command"], "dnf install -y cabextract")

    def test_the_ntsync_step_does_not_ask_again(self):
        args = SimpleNamespace(json=True, yes=False)
        with mock.patch.object(N, "_enable_ntsync") as enable, \
             mock.patch.object(N, "ntsync_status", return_value="active"):
            self.assertEqual(N._ntsync_step(args, True), "active")
            enable.assert_not_called()
            N._ntsync_step(args, False)
            enable.assert_called_once()

    def test_a_failing_ntsync_never_fails_the_packages(self):
        r = subprocess.run(["sh", "-c", "true && { false || true; }"])
        self.assertEqual(r.returncode, 0)
        r = subprocess.run(["sh", "-c", "false && { true || true; }"])
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
