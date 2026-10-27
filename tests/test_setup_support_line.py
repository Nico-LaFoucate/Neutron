#!/usr/bin/env python3
"""The support line after the first `neutron setup` (2026-10-27, his "Yes, do that").

One line under setup's "Done.", only on a first setup in a terminal: never on `neutron update`, a repeated
setup, or `--json` output (Collider parses that).

Run:  python3 tests/test_setup_support_line.py
"""
import importlib.machinery
import importlib.util
import inspect
import os
import unittest

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")
_spec = importlib.util.spec_from_loader("neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N)


class SupportLine(unittest.TestCase):
    def test_first_setup_ends_with_the_support_line(self):
        lines = N.setup_done_lines(updating=False, first=True)
        self.assertTrue(lines[0].startswith("Done."))
        self.assertEqual(lines[-1], N.SUPPORT_LINE)
        self.assertIn("https://neutronproject.org/#support", N.SUPPORT_LINE)

    def test_repeated_setup_and_update_do_not(self):
        self.assertNotIn(N.SUPPORT_LINE, N.setup_done_lines(updating=False, first=False))
        self.assertEqual(N.setup_done_lines(updating=True, first=True), [])
        self.assertEqual(N.setup_done_lines(updating=True, first=False), [])

    def test_only_the_human_summary_prints_it(self):
        src = inspect.getsource(N.cmd_setup)
        human = src.split("if args.json:", 1)[1].split("else:", 1)[1]
        self.assertIn("setup_done_lines(", human)
        self.assertNotIn("SUPPORT_LINE", src.split("if args.json:", 1)[1].split("else:", 1)[0])
        self.assertIn('first = not updating and not inst.get("installed_at")', src)
        # nowhere else in the CLI
        self.assertEqual(inspect.getsource(N).count("SUPPORT_LINE"), 2)   # defined once, used once


if __name__ == "__main__":
    unittest.main()
