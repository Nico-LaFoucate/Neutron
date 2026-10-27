#!/usr/bin/env python3
"""`_prefix_procs` never lists the CLI itself or the processes that started it (2026-10-27).

Fedora 44 KDE live VM, the no-terminal install test: with `export WINEPREFIX=~/Neutron-Prefixes/Test`
in the shell, `neutron prefix provision ~/Neutron-Prefixes/Test` exited 137 with no output. Its own
environ held `WINEPREFIX=<prefix>`, so `_prefix_procs` listed it as an app ("neutron" is not a wine
system process); provision tore down the "leftover helpers" and the sweep SIGKILLed the CLI. A real
wine process in the same prefix must still be listed.

The child here is a python3 run by `sh` with WINEPREFIX set, so both the CLI and its parent carry
the entry. Known-bad: NEUTRON_CLI_UNDER_TEST=<pre-fix copy> fails test_not_self_nor_parent.

Run:  python3 tests/test_prefix_procs_self.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

_CLI = os.environ.get("NEUTRON_CLI_UNDER_TEST") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")

CHILD = r"""
import importlib.machinery, importlib.util, json, os, sys
spec = importlib.util.spec_from_loader("n", importlib.machinery.SourceFileLoader("n", sys.argv[1]))
N = importlib.util.module_from_spec(spec); spec.loader.exec_module(N)
pids = {p for p, _c, _a in N._prefix_procs(os.environ["WINEPREFIX"])}
print(json.dumps({"self": os.getpid() in pids, "parent": os.getppid() in pids,
                  "sibling": int(sys.argv[2]) in pids}))
"""


class NotSelf(unittest.TestCase):
    def test_not_self_nor_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = os.path.join(tmp, "Test")
            os.makedirs(prefix)
            env = dict(os.environ, WINEPREFIX=prefix)
            sibling = subprocess.Popen(["sleep", "30"], env=env)
            try:
                script = os.path.join(tmp, "child.py")
                with open(script, "w") as f:
                    f.write(CHILD)
                # `; true` keeps sh from exec'ing python, so sh stays the parent
                out = subprocess.run(["sh", "-c", f'{sys.executable} "$0" "$1" "$2"; true',
                                      script, _CLI, str(sibling.pid)],
                                     env=env, capture_output=True, text=True, timeout=60)
            finally:
                sibling.kill()
                sibling.wait()
            self.assertTrue(out.stdout.strip(), out.stderr[-800:])
            got = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertFalse(got["self"], "the CLI listed itself as a process of the prefix")
            self.assertFalse(got["parent"], "the CLI listed the shell that ran it")
            self.assertTrue(got["sibling"], "a real process in the prefix must still be listed")


if __name__ == "__main__":
    unittest.main()
