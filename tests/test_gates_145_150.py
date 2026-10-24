#!/usr/bin/env python3
"""The off switches for the fixes shipped in runtimes 11.10-145..150 are listed by `neutron gates` (2026-10-24).

145 (title-bar repaint), 146 (GPU window copy), 147 (Alt repeats, keyboard menu under capture, title-bar clip), 148 and 149
(sideways scrolling) and 150 (Direct2D Flush) shipped with kill switches that `neutron gates` did not list, so
`launch --without <name>` refused them. When a 150 runtime is present, each listed variable must also appear in the
binary that reads it: a typo here would look like a clean negative result, the failure NEUTRON_GATES exists to prevent.

Run:  python3 tests/test_gates_145_150.py      (NEUTRON_TEST_RUNTIME=<runtime dir> to point at a runtime)
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

WIN32U = ["lib/wine/x86_64-unix/win32u.so", "lib/wine/i386-unix/win32u.so"]

# gate name -> (environment variable, the runtime files that read it)
GATES = {
    "caption-settext": ("NEUTRON_CAPTION_BUFFERED", WIN32U),
    "copybits-skip-gpu": ("NEUTRON_COPY_SKIP_GPU", WIN32U),
    "alt-repeat": ("NEUTRON_ALT_REPEAT", WIN32U),
    "capture-keymenu": ("NEUTRON_CAPTURE_KEYMENU", WIN32U),
    "caption-clip": ("NEUTRON_CAPTION_CLIP", WIN32U),
    "hwheel-coords": ("NEUTRON_HWHEEL_COORDS", WIN32U),
    "hwheel-merge": ("NEUTRON_HWHEEL_MERGE", ["bin/wineserver"]),
    "d2d-flush-hold": ("NEUTRON_D2D_FLUSH_HOLD",
                       ["lib/wine/x86_64-windows/d2d1.dll", "lib/wine/i386-windows/d2d1.dll"]),
}


def _runtime():
    for d in (os.environ.get("NEUTRON_TEST_RUNTIME"),
              os.path.expanduser("~/.local/share/neutron/runtimes/neutron-wine-11.10-150"),
              "/var/tmp/neutron-i19/rt150/neutron-wine-11.10-150"):
        if d and os.path.isdir(d):
            return d
    return None


class Gates145To150(unittest.TestCase):
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
            self.skipTest("no 11.10-150 runtime here")
        for name, (env, files) in GATES.items():
            for rel in files:
                with open(os.path.join(rt, rel), "rb") as f:
                    data = f.read()
                self.assertTrue(env.encode() in data, "%s not in %s" % (env, rel))
                # the check can fail: a name the runtime does not read is not found
                self.assertFalse((env + "_TYPO").encode() in data)


if __name__ == "__main__":
    unittest.main()
