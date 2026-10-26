#!/usr/bin/env python3
"""The off switch for runtime 11.10-151's vkd3d-proton fix (Neutron#36) is listed by `neutron gates` (2026-10-25).

151 keeps a closed Direct3D 12 command list's allocator alive (vkd3d-proton 0003; Illustrator's Image Trace crashed in
winevulkan's vkQueueSubmit2 thunk without it). Its kill switch NEUTRON_VKD3D_LIST_KEEPS_ALLOCATOR=0 must be reachable as
`launch --without vkd3d-list-keeps-allocator`, and the 151 d3d12core.dll must read that exact name.

Run:  python3 tests/test_gates_151.py      (NEUTRON_TEST_RUNTIME=<runtime dir> to point at a runtime)
"""
import importlib.machinery
import importlib.util
import os
import unittest

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()

NAME, ENV = "vkd3d-list-keeps-allocator", "NEUTRON_VKD3D_LIST_KEEPS_ALLOCATOR"
READER = "lib/wine/vkd3d-proton/x86_64-windows/d3d12core.dll"


def _runtime():
    for d in (os.environ.get("NEUTRON_TEST_RUNTIME"),
              os.path.expanduser("~/.local/share/neutron/runtimes/neutron-wine-11.10-151"),
              "/var/tmp/neutron-i19/rt151/neutron-wine-11.10-151"):
        if d and os.path.isdir(d):
            return d
    return None


class Gate151(unittest.TestCase):
    def test_listed_and_on_by_default(self):
        self.assertIn(NAME, N.NEUTRON_GATES)
        self.assertEqual(N.NEUTRON_GATES[NAME]["env"], ENV)
        self.assertTrue(N.NEUTRON_GATES[NAME]["default"])

    def test_without_turns_it_off(self):
        self.assertEqual(N.gate_env(NAME, False), (ENV, "0"))

    def test_runtime_reads_the_variable(self):
        rt = _runtime()
        if not rt:
            self.skipTest("no 11.10-151 runtime here")
        with open(os.path.join(rt, READER), "rb") as f:
            data = f.read()
        self.assertTrue(ENV.encode() in data, "%s not in %s" % (ENV, READER))
        self.assertFalse((ENV + "_TYPO").encode() in data)   # the check can fail


if __name__ == "__main__":
    unittest.main()
