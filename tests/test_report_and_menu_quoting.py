#!/usr/bin/env python3
"""Menu entries quote the prefix path, `neutron doctor` reads as text, and `neutron report` (2026-10-25).

1. A prefix path with a space was written bare into the menu entry's Exec line, so the desktop ran
   `neutron launch ... --prefix /home/a` and handed `b` over as a file to open. The entry is now quoted
   as the Desktop Entry Specification says, and checked here with GLib's own parser (the one GNOME
   uses; KDE follows the same rules). The CLI's own readers of those entries (`prefix list`, `update`)
   must find the path too.
2. `neutron doctor` without --json printed a Python list of dicts.
3. `neutron report`: one paste for a bug report, with the home folder, user name, full name, computer
   name, email addresses and tokens replaced.

Run:  python3 tests/test_report_and_menu_quoting.py
"""
import importlib.machinery
import importlib.util
import io
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")

try:
    import gi
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib
except (ImportError, ValueError):
    GLib = None


def _load_cli(env):
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_loader(
            "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def _glib_exec_argv(desktop_file):
    """argv as GLib builds it from a .desktop file: the string value unescaped, then shell-split."""
    kf = GLib.KeyFile()
    kf.load_from_file(desktop_file, GLib.KeyFileFlags.NONE)
    ok, argv = GLib.shell_parse_argv(kf.get_string("Desktop Entry", "Exec"))
    return argv


class FakeHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="neutron-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = {"HOME": self.home, "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                    "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_CACHE_HOME": os.path.join(self.home, ".cache")}
        self.cli = _load_cli(self.env)

    def fake_prefix(self, name):
        prefix = os.path.join(self.home, name)
        exe = os.path.join(prefix, self.cli.APP_PROFILES["photoshop"]["exe"])
        os.makedirs(os.path.dirname(exe))
        open(exe, "wb").close()
        return prefix

    def write_entries(self, prefix):
        cli = self.cli
        with mock.patch.dict(os.environ, self.env), \
                mock.patch.object(cli, "refresh_desktop_caches", return_value={}), \
                mock.patch.object(cli, "install_neutron_mime_package", return_value=None), \
                mock.patch.object(cli, "repair_mime_defaults", return_value=[]):
            return cli.register_app_desktop_entries(prefix)


@unittest.skipIf(GLib is None, "needs python-gobject (GLib) to parse desktop entries as a desktop does")
class MenuEntryQuoting(FakeHome):
    def test_prefix_with_a_space_reaches_launch_whole(self):
        prefix = self.fake_prefix("Adobe Prefixes/My Suite")
        out = self.write_entries(prefix)
        self.assertEqual(len(out["entries"]), 1)
        entry = os.path.join(self.cli.APPS_DIR, out["entries"][0]["file"])
        argv = _glib_exec_argv(entry)
        self.assertIn("--prefix", argv)
        self.assertEqual(argv[argv.index("--prefix") + 1], prefix)
        # The CLI's own readers of the entry find the same prefix.
        self.assertIn(os.path.realpath(prefix), self.cli.neutron_prefixes())

    def test_desktop_file_validate_accepts_the_entry(self):
        if not shutil.which("desktop-file-validate"):
            self.skipTest("desktop-file-validate is not installed")
        prefix = self.fake_prefix("with space")
        out = self.write_entries(prefix)
        entry = os.path.join(self.cli.APPS_DIR, out["entries"][0]["file"])
        r = subprocess.run(["desktop-file-validate", entry], capture_output=True, text=True)
        self.assertNotIn("error", (r.stdout + r.stderr).lower(), r.stdout + r.stderr)

    def test_plain_path_is_written_as_before(self):
        prefix = self.fake_prefix(".premiere2025")
        out = self.write_entries(prefix)
        with open(os.path.join(self.cli.APPS_DIR, out["entries"][0]["file"])) as f:
            body = f.read()
        self.assertRegex(body, r" --prefix %s( %%f)?\n" % re.escape(prefix))

    def test_awkward_arguments_round_trip(self):
        for s in ["/home/a b/Adobe 2026", "/p/it's", '/p/"q"', "/p/$HOME", "/p/back\\slash",
                  "/p/100%", "/p/`x`", "/p/a;b&c|d", "/p/~x", "/p/(x)", "/p/tab\there"]:
            arg = self.cli.desktop_exec_arg(s)
            path = os.path.join(self.home, "t.desktop")
            with open(path, "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=t\nExec=env %s\n" % arg)
            glib = _glib_exec_argv(path)
            self.assertEqual([a.replace("%%", "%") for a in glib[1:]], [s], arg)
            self.assertEqual(self.cli.desktop_exec_args("env " + arg)[1:], [s], arg)


class DoctorText(FakeHome):
    def test_verdicts(self):
        t = self.cli.doctor_text
        ok = {"name": "wine", "ok": True, "detail": "/x/wine"}
        self.assertEqual(t([ok]).splitlines()[0], "Neutron doctor: healthy")
        bad = {"name": "lib32", "ok": False, "detail": "missing"}
        warn = {"name": "ntsync", "ok": True, "warning": True, "detail": "off"}
        pend = {"name": "display_fix", "ok": True, "pending": True, "detail": "pending"}
        opt = {"name": "exiftool", "ok": False}
        lines = t([ok, bad, warn, pend, opt]).splitlines()
        self.assertEqual(lines[0], "Neutron doctor: 1 problem: lib32 (1 warning)")
        self.assertEqual([l.split()[0] for l in lines[1:]], ["ok", "PROBLEM", "warning", "pending", "optional"])
        self.assertTrue(self.cli.doctor_healthy([ok, opt]))

    def test_human_doctor_prints_no_python_structures(self):
        args = self.cli.build_parser().parse_args(["doctor"])
        buf = io.StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(buf):
            self.cli.cmd_doctor(args)
        text = buf.getvalue()
        self.assertTrue(text.startswith("Neutron doctor: "), text[:200])
        self.assertNotIn("checks: [", text)
        self.assertNotIn("{'name'", text)


class Redact(FakeHome):
    def test_personal_details_are_replaced(self):
        ident = (["/var/home/jdoe", "/home/jdoe"], "jdoe", ["Jane Doe", "Jane", "Doe"], "janes-laptop")
        raw = ("/var/home/jdoe/x /home/jdoe/.premiere2025 C:\\users\\jdoe\\AppData Z:\\home\\jdoe\\p "
               "signed in as jane.doe+adobe@example.com, Jane Doe on janes-laptop "
               "Authorization: Bearer abc.def-123 token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig "
               "https://ims-na1.adobelogin.com/ims/check?client_id=x&access_token=secret "
               '"refresh_token": "zzz" mac 00:1a:2b:3c:4d:5e version 26.5.2.5 /usr/lib/x')
        out = self.cli.redact(raw, ident)
        for leak in ("jdoe", "Jane", "Doe", "janes-laptop", "example.com", "abc.def-123", "eyJhbGci",
                     "secret", "zzz", "client_id", "00:1a:2b"):
            self.assertNotIn(leak, out)
        self.assertIn("~/x ~/.premiere2025 C:\\users\\<user>\\AppData Z:\\home\\<user>\\p", out)
        self.assertIn("version 26.5.2.5 /usr/lib/x", out)    # versions and system paths survive


def _tiny_pe(version):
    """A PE32+ with one .rsrc section holding a VS_FIXEDFILEINFO."""
    a, b, c, d = version
    pe = bytearray(0x600)
    struct.pack_into("<2sI", pe, 0, b"MZ", 0)
    struct.pack_into("<I", pe, 0x3c, 0x40)
    pe[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", pe, 0x44, 0x8664, 1, 0, 0, 0, 240, 0x22)
    opt = 0x58
    struct.pack_into("<H", pe, opt, 0x20b)
    struct.pack_into("<II", pe, opt + 112 + 2 * 8, 0x1000, 0x200)       # resource directory
    sh = opt + 240
    pe[sh:sh + 8] = b".rsrc\0\0\0"
    struct.pack_into("<IIII", pe, sh + 8, 0x200, 0x1000, 0x200, 0x400)  # vsize, va, rawsize, raw
    struct.pack_into("<IIII", pe, 0x410, 0xFEEF04BD, 0x10000, (a << 16) | b, (c << 16) | d)
    return bytes(pe)


class Pieces(FakeHome):
    def test_file_version(self):
        exe = os.path.join(self.home, "app.exe")
        with open(exe, "wb") as f:
            f.write(_tiny_pe((26, 5, 2, 5)))
        self.assertEqual(self.cli._pe_file_version(exe), "26.5.2.5")
        open(exe, "wb").close()
        self.assertIsNone(self.cli._pe_file_version(exe))

    def test_tail_of_a_big_log(self):
        log = os.path.join(self.home, "big.log")
        with open(log, "w") as f:
            for i in range(200000):
                f.write("line %d\n" % i)
        self.assertEqual(self.cli._tail_lines(log, 3), ["line 199997", "line 199998", "line 199999"])


class Report(FakeHome):
    def run_report(self, *argv):
        args = self.cli.build_parser().parse_args(["report", *argv])
        buf = io.StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(buf):
            rc = self.cli.cmd_report(args)
        return rc, buf.getvalue()

    def test_report_has_the_form_fields_and_no_home(self):
        prefix = self.fake_prefix("My Prefix")
        os.makedirs(self.cli.NEUTRON_LOGS_DIR)
        with open(os.path.join(self.cli.NEUTRON_LOGS_DIR, "photoshop-my-prefix-20261025-120000.log"), "w") as f:
            f.write("starting %s/drive_c\nlast line\n" % prefix)
        rc, text = self.run_report("--prefix", prefix, "--app", "photoshop")
        self.assertEqual(rc, 0)
        for title in ("Distribution", "Desktop and session", "GPU and driver", "neutron --version",
                      "neutron doctor", "Prefixes", "Display", "Log: photoshop-"):
            self.assertIn("== " + title, text)
        self.assertNotIn(self.home, text)
        self.assertIn("starting ~/My Prefix/drive_c\nlast line", text)

    def test_unknown_prefix_is_refused(self):
        args = self.cli.build_parser().parse_args(["report", "--prefix", os.path.join(self.home, "nope")])
        with mock.patch.dict(os.environ, self.env), redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as cm:
            self.cli.cmd_report(args)
        self.assertEqual(cm.exception.code, self.cli.EX_BADPREFIX)


if __name__ == "__main__":
    unittest.main()
