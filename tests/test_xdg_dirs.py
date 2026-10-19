#!/usr/bin/env python3
"""Tests for the XDG base directories (2026-10-19): an EMPTY or relative XDG_*_HOME means the default.

The 11.10-138 fresh-HOME test ran `neutron setup` with XDG_DATA_HOME, XDG_CONFIG_HOME and XDG_CACHE_HOME set to "".
The CLI joined "" as a path, so runtimes, menu entries and the rest landed under the current directory instead of
~/.local/share. The XDG Base Directory spec: unset or empty means the default, and a relative value is invalid and
must be ignored. Nothing here installs anything; the CLI is loaded with a temp HOME and each module-level path is read.

Run:  python3 tests/test_xdg_dirs.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli(env):
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_loader(
            "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


class XdgDirs(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.share = os.path.join(self.home, ".local", "share")

    def data_paths(self, cli):
        return (cli.NEUTRON_DATA_DIR, cli.NEUTRON_RUNTIMES_DIR, cli.NEUTRON_LOGS_DIR, cli.APPS_DIR)

    def default_data_paths(self):
        return (os.path.join(self.share, "neutron"), os.path.join(self.share, "neutron", "runtimes"),
                os.path.join(self.share, "neutron", "logs"), os.path.join(self.share, "applications"))

    def test_empty_means_default(self):
        cli = _load_cli({"HOME": self.home, "XDG_DATA_HOME": "", "XDG_CONFIG_HOME": "", "XDG_CACHE_HOME": ""})
        self.assertEqual(self.data_paths(cli), self.default_data_paths())
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "XDG_CACHE_HOME": ""}):
            self.assertEqual(cli._xdg_dir("XDG_CONFIG_HOME", ".config"), os.path.join(self.home, ".config"))
            self.assertEqual(cli._xdg_dir("XDG_CACHE_HOME", ".cache"), os.path.join(self.home, ".cache"))

    def test_relative_is_ignored(self):
        cli = _load_cli({"HOME": self.home, "XDG_DATA_HOME": "data"})
        self.assertEqual(self.data_paths(cli), self.default_data_paths())

    def test_unset_means_default(self):
        env = {"HOME": self.home}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_DATA_HOME", None)
            cli = _load_cli(env)
        self.assertEqual(self.data_paths(cli), self.default_data_paths())

    def test_absolute_is_used(self):
        data = os.path.join(self.home, "elsewhere")
        cli = _load_cli({"HOME": self.home, "XDG_DATA_HOME": data})
        self.assertEqual(self.data_paths(cli),
                         (os.path.join(data, "neutron"), os.path.join(data, "neutron", "runtimes"),
                          os.path.join(data, "neutron", "logs"), os.path.join(data, "applications")))


if __name__ == "__main__":
    unittest.main()
