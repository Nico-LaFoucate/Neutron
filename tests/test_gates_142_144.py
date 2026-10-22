#!/usr/bin/env python3
"""The off switches for the fixes shipped in runtimes 11.10-142..144 are listed by `neutron gates` (2026-10-22).

142 (pen side buttons), 143 (smooth scrolling) and 144 (msxml3 embedded XML declarations, big-endian PCM audio) shipped
with kill switches that `neutron gates` did not list, so `launch --without <name>` refused them. When a 144 runtime is
present, each listed variable must also appear in the binary that reads it: a typo here would look like a clean
negative result, the failure NEUTRON_GATES exists to prevent.

Run:  python3 tests/test_gates_142_144.py      (NEUTRON_TEST_RUNTIME=<runtime dir> to point at a runtime)
"""
import importlib.machinery
import importlib.util
import os
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()

# gate name -> (environment variable, the runtime files that read it)
GATES = {
    "pen-buttons": ("NEUTRON_PEN_BUTTONS", ["lib/wine/x86_64-unix/winewayland.so", "lib/wine/i386-unix/winewayland.so"]),
    "smooth-scroll": ("NEUTRON_SMOOTH_SCROLL", ["lib/wine/x86_64-unix/winewayland.so", "lib/wine/i386-unix/winewayland.so"]),
    "msxml-embedded-xmldecl": ("NEUTRON_MSXML_EMBEDDED_XMLDECL",
                               ["lib/wine/x86_64-windows/msxml3.dll", "lib/wine/i386-windows/msxml3.dll"]),
    "big-endian-pcm": ("NEUTRON_BIG_ENDIAN_PCM",
                       ["lib/wine/x86_64-unix/winegstreamer.so", "lib/wine/i386-unix/winegstreamer.so"]),
}


def _runtime():
    for d in (os.environ.get("NEUTRON_TEST_RUNTIME"),
              os.path.expanduser("~/.local/share/neutron/runtimes/neutron-wine-11.10-144"),
              "/var/tmp/neutron-i19/rt144/neutron-wine-11.10-144"):
        if d and os.path.isdir(d):
            return d
    return None


class Gates142To144(unittest.TestCase):
    def test_listed_and_on_by_default(self):
        for name, (env, _) in GATES.items():
            self.assertIn(name, N.NEUTRON_GATES)
            self.assertEqual(N.NEUTRON_GATES[name]["env"], env)
            self.assertTrue(N.NEUTRON_GATES[name]["default"])

    def test_without_turns_each_off(self):
        for name, (env, _) in GATES.items():
            self.assertEqual(N.gate_env(name, False), (env, "0"))

    def test_runtime_reads_each_variable(self):
        rt = _runtime()
        if not rt:
            self.skipTest("no 11.10-144 runtime here")
        for name, (env, files) in GATES.items():
            for rel in files:
                with open(os.path.join(rt, rel), "rb") as f:
                    data = f.read()
                self.assertTrue(env.encode() in data, "%s not in %s" % (env, rel))
                # the check can fail: a name the runtime does not read is not found
                self.assertFalse((env + "_TYPO").encode() in data)


if __name__ == "__main__":
    unittest.main()
