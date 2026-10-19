#!/usr/bin/env python3
"""Tests for doctor's `prefix-files` check (2026-10-19, GitHub Neutron#29).

The reporter's prefix had system.reg, user.reg and .update-timestamp that their user could not read, while drive_c read
fine, and `neutron doctor` said healthy: every check that reads those files took OSError as "cannot tell" and passed.
`_prefix_file_problems()` now names each bad file, who owns it, and the fix. Nothing here starts wine; the prefix is a
temp dir, and "owned by someone else" is simulated by making os.getuid() return another id.

Run:  python3 tests/test_prefix_files.py
"""
import importlib.machinery
import importlib.util
import os
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


class PrefixFiles(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-pf-")
        os.makedirs(os.path.join(self.prefix, "drive_c"))
        for name in ("system.reg", "user.reg", ".update-timestamp"):
            with open(os.path.join(self.prefix, name), "w") as f:
                f.write("x")

    def tearDown(self):
        for name in ("system.reg", "user.reg", ".update-timestamp"):
            path = os.path.join(self.prefix, name)
            if os.path.exists(path):
                os.chmod(path, 0o644)

    def test_a_healthy_prefix_has_no_problems(self):
        self.assertEqual(N._prefix_file_problems(self.prefix), [])

    def test_unreadable_registry_is_named_with_the_fix(self):
        os.chmod(os.path.join(self.prefix, "user.reg"), 0)
        got = N._prefix_file_problems(self.prefix)
        self.assertTrue(any(p == "user.reg: its permissions don't let you read it" for p in got), got)
        self.assertTrue(any("chmod u+rw" in p for p in got), got)
        self.assertFalse(any("system.reg" in p for p in got), got)

    def test_missing_stamp_points_at_provision(self):
        os.remove(os.path.join(self.prefix, ".update-timestamp"))
        got = N._prefix_file_problems(self.prefix)
        self.assertIn(".update-timestamp is missing", got)
        self.assertTrue(any("neutron prefix provision" in p for p in got), got)

    def test_files_of_another_user_point_at_chown(self):
        """The #29 shape: everything belongs to someone else (sudo). Faked by changing who "we" are."""
        with mock.patch.object(N.os, "getuid", return_value=os.getuid() + 1):
            got = N._prefix_file_problems(self.prefix)
        self.assertTrue(any(p.startswith("the prefix folder belongs to") for p in got), got)
        self.assertTrue(any(p.startswith("system.reg belongs to") for p in got), got)
        self.assertTrue(any("sudo chown -R" in p and self.prefix in p for p in got), got)


if __name__ == "__main__":
    unittest.main()
