#!/usr/bin/env python3
"""Provision starts wineboot with WINEBOOT_HIDE_DIALOG=1 (2026-10-25).

`neutron prefix provision` runs `wineboot -u -r`; `-u` forces a prefix update, and Wine showed its "The Wine
configuration in ... is being updated, please wait..." window on every provision, so on every Mud Hut install and
update. Runtime 11.10-152 (patch 74) skips that window when WINEBOOT_HIDE_DIALOG is set. This runs the CLI with a
stand-in `wine` that records its environment and then fails, so provision stops right after wineboot.

Run:  python3 tests/test_provision_hides_wineboot_window.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


class ProvisionHidesWinebootWindow(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="neutron-wbhide-")
        bindir = os.path.join(self.home, "runtime", "bin")
        os.makedirs(bindir)
        self.record = os.path.join(self.home, "wine-env.txt")
        with open(os.path.join(bindir, "wine"), "w") as f:
            f.write('#!/bin/sh\nif [ "$1" = wineboot ]; then echo "args=$* hide=${WINEBOOT_HIDE_DIALOG-unset}" >> "%s"; fi\n'
                    "exit 1\n" % self.record)
        with open(os.path.join(bindir, "wineserver"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        for n in ("wine", "wineserver"):
            os.chmod(os.path.join(bindir, n), 0o755)
        self.wine = os.path.join(bindir, "wine")
        self.prefix = os.path.join(self.home, "prefix")
        os.makedirs(os.path.join(self.prefix, "drive_c"))

    def tearDown(self):
        shutil.rmtree(self.home)

    def run_provision(self, *extra):
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "USER": "tester", "NEUTRON_WINE": self.wine,
               "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
               "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
               "XDG_CACHE_HOME": os.path.join(self.home, ".cache")}
        subprocess.run([sys.executable, _CLI, "--json", "prefix", "provision", *extra, self.prefix], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        with open(self.record) as f:
            return f.read()

    def test_wineboot_runs_with_the_window_hidden(self):
        rec = self.run_provision()
        self.assertIn("args=wineboot -u -r", rec)
        self.assertIn("hide=1", rec)

    def test_microsoft_only_too(self):
        # Mud Hut's step before Adobe's installer
        self.assertIn("hide=1", self.run_provision("--microsoft-only"))


if __name__ == "__main__":
    unittest.main()
