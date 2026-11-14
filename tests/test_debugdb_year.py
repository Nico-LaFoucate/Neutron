#!/usr/bin/env python3
"""With two yearly versions installed, the live Debug Database is the newest year's (2026-11-14).

After Effects 2027 (27.0) installed beside 2026 (26.0): `launch` starts 2027, but find_debug_databases ranked the
genuine databases by line count before version and picked 26.0 (207 lines) over 27.0 (206), so the DirectX-display
fix and Collider's status went to the 2026 file. The major version now ranks before the key count. The older
26.0-vs-26.3 case still holds: After Effects 2026 keeps a genuine 26.0 database and a 3-line stub at 26.3, and the
marker picks 26.0.

Nothing here starts wine.

Run:  python3 tests/test_debugdb_year.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_programs as tp                          # noqa: E402


def _db(root, user, subdir, ver, lines, marker=True):
    d = os.path.join(root, "drive_c", "users", user, "AppData", "Roaming", "Adobe", subdir, ver)
    os.makedirs(d, exist_ok=True)
    body = ("AEDebugDatabaseVersion\t1\n" if marker else "") + "".join("Key%d\t0\n" % i for i in range(lines))
    with open(os.path.join(d, "Debug Database.txt"), "w") as f:
        f.write(body)
    return os.path.join(d, "Debug Database.txt")


class DebugDatabaseYear(unittest.TestCase):
    def setUp(self):
        self.cli = tp._load_cli({})
        self.tmp = tempfile.TemporaryDirectory()
        self.p = self.tmp.name
        os.makedirs(os.path.join(self.p, "drive_c", "Program Files", "Adobe", "Adobe After Effects 2026"))

    def tearDown(self):
        self.tmp.cleanup()

    def pick(self):
        return dict((label, path) for label, path, _ in self.cli.find_debug_databases(self.p, "u"))["aftereffects"]

    def test_newest_year_wins_over_more_keys(self):
        _db(self.p, "u", "After Effects", "26.0", 207)
        new = _db(self.p, "u", "After Effects", "27.0", 206)
        self.assertEqual(self.pick(), new)

    def test_genuine_still_beats_stub_within_one_year(self):
        real = _db(self.p, "u", "After Effects", "26.0", 184)
        _db(self.p, "u", "After Effects", "26.3", 2, marker=False)
        self.assertEqual(self.pick(), real)

    def test_genuine_newest_year_beats_newer_stub(self):
        _db(self.p, "u", "After Effects", "26.0", 184)
        new = _db(self.p, "u", "After Effects", "27.0", 180)
        _db(self.p, "u", "After Effects", "27.1", 2, marker=False)
        self.assertEqual(self.pick(), new)


if __name__ == "__main__":
    unittest.main()
