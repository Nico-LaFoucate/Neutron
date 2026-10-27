#!/usr/bin/env python3
"""In --json mode an unexpected exception still ends with {ok: false, reason} on stdout (2026-10-27).

Fedora 44 KDE live VM, the no-terminal install test: the live session's 2.4 GB root filled up while
`neutron setup` wrote installed.json. The CLI died with a Python traceback on stderr, and Collider,
which reads stdout only, showed "neutron setup --install-prereqs exited with code 1". Human mode
keeps the plain traceback.

Known-bad: NEUTRON_CLI_UNDER_TEST=<pre-fix copy> fails both json tests (the exception escapes).

Run:  python3 tests/test_uncaught_error_json.py
"""
import contextlib
import errno
import importlib.machinery
import importlib.util
import io
import json
import os
import unittest
from unittest import mock

_CLI = os.environ.get("NEUTRON_CLI_UNDER_TEST") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


def _run(argv, err):
    out, stderr = io.StringIO(), io.StringIO()
    with mock.patch.object(N, "cmd_setup", side_effect=err), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(stderr):
        code = N.main(argv)
    return code, out.getvalue(), stderr.getvalue()


class UncaughtJson(unittest.TestCase):
    def test_disk_full_reads_as_a_reason(self):
        err = OSError(errno.ENOSPC, "No space left on device", "/home/u/.local/share/neutron/installed.json.part")
        code, out, stderr = _run(["--json", "setup"], err)
        self.assertEqual(code, N.EX_FAIL)
        obj = json.loads(out.strip().splitlines()[-1])
        self.assertIs(obj["ok"], False)
        self.assertIn("No space left on device", obj["reason"])
        self.assertIn("neutron setup stopped", obj["reason"])
        self.assertIn("Traceback", stderr, "the traceback still goes to stderr")

    def test_other_exception_names_its_type(self):
        code, out, _ = _run(["--json", "setup"], KeyError("installed_at"))
        obj = json.loads(out.strip().splitlines()[-1])
        self.assertIn("KeyError", obj["reason"])

    def test_human_mode_keeps_the_traceback(self):
        with self.assertRaises(KeyError):
            _run(["setup"], KeyError("installed_at"))


if __name__ == "__main__":
    unittest.main()
