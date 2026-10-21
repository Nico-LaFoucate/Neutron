#!/usr/bin/env python3
"""Tests for `neutron prefix provision` when Wine cannot start in the prefix (2026-10-21, GitHub Neutron#29).

The reporter's prefix had the Adobe files, Microsoft's DLLs, WebView2 and the DXVK configs, but no system.reg, user.reg,
.update-timestamp or dosdevices: Wine had never started in it. Provision ran every step after a failed wineboot and
reported ok, so Mud Hut and Collider took it for a working prefix and the user learned at launch, from a message about a
missing runtime stamp. Provision now stops after wineboot when it wrote no registry, says so with Wine's own output, and
installs nothing else. These run the CLI with a stand-in `wine` that fails the way a Wine that cannot start does.

Run:  python3 tests/test_provision_wine_fails.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


class ProvisionWhenWineCannotStart(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="neutron-provfail-")
        bindir = os.path.join(self.home, "runtime", "bin")
        os.makedirs(bindir)
        for name in ("wine", "wineserver"):
            path = os.path.join(bindir, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\necho 'wine: could not load ntdll.so: simulated' >&2\nexit 1\n")
            os.chmod(path, 0o755)
        self.wine = os.path.join(bindir, "wine")
        self.prefix = os.path.join(self.home, "prefix")
        os.makedirs(os.path.join(self.prefix, "drive_c", "Program Files", "Adobe", "Adobe Photoshop 2026"))

    def tearDown(self):
        shutil.rmtree(self.home)

    def provision(self, *extra):
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "USER": "tester", "NEUTRON_WINE": self.wine,
               "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
               "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
               "XDG_CACHE_HOME": os.path.join(self.home, ".cache")}
        p = subprocess.run([sys.executable, _CLI, "--json", "prefix", "provision", *extra, self.prefix], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=300)
        lines = [l for l in p.stdout.decode().splitlines() if l.strip().startswith("{")]
        return p.returncode, json.loads(lines[-1])

    def test_fails_and_says_why(self):
        rc, out = self.provision()
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertIn("Wine could not set up this prefix", out["reason"])
        self.assertIn("exited with 1", out["reason"])
        self.assertIn("wine: could not load ntdll.so: simulated", out["wine_output"])
        self.assertIn("wineboot --init", out["fix"])
        self.assertEqual([s["step"] for s in out["steps"]], ["init"])

    def test_installs_nothing_else(self):
        self.provision()
        left = sorted(os.listdir(self.prefix))
        self.assertEqual(left, ["drive_c"])   # no DXVK configs, staged natives, Microsoft DLLs or fonts
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "drive_c", "windows")))

    def test_microsoft_only_stops_too(self):
        # Mud Hut runs this before Adobe's installer
        rc, out = self.provision("--microsoft-only")
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertIn("Wine could not set up this prefix", out["reason"])

    def test_wine_output_is_logged(self):
        _, out = self.provision()
        self.assertTrue(out["log"] and os.path.isfile(out["log"]))
        with open(out["log"]) as f:
            self.assertIn("simulated", f.read())


if __name__ == "__main__":
    unittest.main()
