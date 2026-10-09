#!/usr/bin/env python3
"""Tests for removing the old Premiere home-screen KWin rule (bin/neutron: _kwin_home_rule_remove).

`neutron window-rule` and Collider's home-screen setting were removed in 1.0.0-beta.2 (their rule
only ever matched Premiere's splash). `setup`, `update` and `uninstall` now take down a rule an
earlier version installed. These tests fake kreadconfig/kwriteconfig and check what would be
written: the user's own rules must survive, and nothing may be written when there is no rule.

Run:  python3 tests/test_kwin_rule_cleanup.py
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


class FakeKConfig:
    """A tiny kwinrulesrc in memory, driven through the same argv the CLI passes."""

    def __init__(self, groups):
        self.groups = {g: dict(kv) for g, kv in groups.items()}
        self.writes = []

    def run(self, argv, **kw):
        tool = os.path.basename(argv[0])
        group = argv[argv.index("--group") + 1] if "--group" in argv else None
        key = argv[argv.index("--key") + 1] if "--key" in argv else None
        if tool.startswith("kreadconfig"):
            out = self.groups.get(group, {}).get(key, "")
            return subprocess.CompletedProcess(argv, 0, stdout=out + "\n", stderr="")
        if tool.startswith("kwriteconfig"):
            self.writes.append(argv)
            if "--delete" in argv:
                self.groups.get(group, {}).pop(key, None)
            else:
                self.groups.setdefault(group, {})[key] = argv[-1]
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")   # gdbus reconfigure


class KwinRuleCleanup(unittest.TestCase):
    def setUp(self):
        self._saved = (N._is_kde, N.have, N.subprocess.run)
        N._is_kde = lambda: True
        N.have = lambda cmd: True

    def tearDown(self):
        N._is_kde, N.have, N.subprocess.run = self._saved

    def _use(self, fake):
        N.subprocess.run = fake.run

    def test_removes_old_rule_and_keeps_the_users_rules(self):
        fake = FakeKConfig({
            "General": {"rules": "users-rule,neutron-premiere-home", "count": "2"},
            "neutron-premiere-home": {"wmclass": "neutron-premiere-", "position": "0,82",
                                      "positionrule": "2"},
            "users-rule": {"wmclass": "firefox"}})
        self._use(fake)
        self.assertTrue(N._kwin_home_rule_remove())
        self.assertEqual(fake.groups["General"], {"rules": "users-rule", "count": "1"})
        self.assertEqual(fake.groups["neutron-premiere-home"], {})       # every key deleted
        self.assertEqual(fake.groups["users-rule"], {"wmclass": "firefox"})

    def test_orphaned_stanza_is_removed_too(self):
        # The id dropped from rules= but the Force keys left behind (the 2026-09-01 lesson).
        fake = FakeKConfig({"General": {"rules": "", "count": "0"},
                            "neutron-premiere-home": {"positionrule": "2", "position": "0,82"}})
        self._use(fake)
        self.assertTrue(N._kwin_home_rule_remove())
        self.assertEqual(fake.groups["neutron-premiere-home"], {})

    def test_no_rule_means_no_writes(self):
        fake = FakeKConfig({"General": {"rules": "users-rule", "count": "1"},
                            "users-rule": {"wmclass": "firefox"}})
        self._use(fake)
        self.assertFalse(N._kwin_home_rule_remove())
        self.assertEqual(fake.writes, [])

    def test_not_kde_is_a_no_op(self):
        fake = FakeKConfig({"General": {"rules": "neutron-premiere-home"}})
        self._use(fake)
        N._is_kde = lambda: False
        self.assertFalse(N._kwin_home_rule_remove())
        self.assertEqual(fake.writes, [])

    def test_window_rule_command_is_gone(self):
        src = open(_CLI).read()
        self.assertNotIn('add_parser("window-rule"', src)
        self.assertNotIn("def cmd_window_rule", src)


if __name__ == "__main__":
    unittest.main()
