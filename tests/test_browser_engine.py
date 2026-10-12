#!/usr/bin/env python3
"""Tests for detecting whether Wine's browser engine is registered (bin/neutron:
_mshtml_protocols_registered, used by provision's mshtml_register step and doctor's
browser-engine check).

Mud Hut creates prefixes with mshtml disabled, so Wine never registered its about: protocol
handler; every embedded browser that starts at about:blank stayed empty (Lightroom Classic's
About box, GitHub issue Neutron#10). The check reads system.reg for the handler key, written
exactly as Wine writes it (doubled backslashes).

Run:  python3 tests/test_browser_engine.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLI = _load_cli()

REGISTERED = (
    'WINE REGISTRY Version 2\n\n'
    '[Software\\\\Classes\\\\PROTOCOLS\\\\Handler\\\\about] 1791761897\n'
    '#time=1dd5a3c0e0b1b2c\n'
    '"CLSID"="{3050F406-98B5-11CF-BB82-00AA00BDCE0B}"\n\n'
    '[Software\\\\Classes\\\\PROTOCOLS\\\\Handler\\\\http] 1791761897\n'
)
UNREGISTERED = (
    'WINE REGISTRY Version 2\n\n'
    '[Software\\\\Classes\\\\PROTOCOLS\\\\Handler\\\\file] 1791761897\n'
    '[Software\\\\Classes\\\\PROTOCOLS\\\\Handler\\\\http] 1791761897\n'
    '[Software\\\\Classes\\\\PROTOCOLS\\\\Handler\\\\https] 1791761897\n'
    # a value that merely mentions about: must not count
    '"Url"="about:blank"\n'
)


class BrowserEngineRegistered(unittest.TestCase):
    def _prefix(self, content):
        d = tempfile.mkdtemp(prefix="neutron-mshtml-test-")
        if content is not None:
            with open(os.path.join(d, "system.reg"), "w") as f:
                f.write(content)
        return d

    def test_registered(self):
        self.assertIs(CLI._mshtml_protocols_registered(self._prefix(REGISTERED)), True)

    def test_not_registered(self):
        self.assertIs(CLI._mshtml_protocols_registered(self._prefix(UNREGISTERED)), False)

    def test_unreadable_is_unknown(self):
        self.assertIsNone(CLI._mshtml_protocols_registered(self._prefix(None)))


if __name__ == "__main__":
    unittest.main()
