#!/usr/bin/env python3
"""Tests for stage_natives' cleanup of DLLs a runtime no longer lists, and for the hint `neutron update`
prints about prefixes on another runtime.

The case that started it (2026-10-16): pre-release 11.10-128 added amfrt64.dll (AMD hardware encoding)
with the override `amfrt64=native`. Going back to 11.10-127 with a plain `neutron update` left both in
the prefix, because staging only ever added. Now each staging records what it put into the prefix
(<prefix>/neutron-natives-staged.json) and removes what the current runtime no longer lists:
  * the file only while it is byte-for-byte what Neutron staged (a DLL the user or an app replaced
    stays, and so does its override);
  * the override only when nothing Neutron writes still wants that key.
A prefix from before the record is cleaned only of system32/amfrt64.dll, and only when it is exactly
11.10-128's build, read from an installed 11.10-128.

Everything runs on fake runtimes and prefixes in a temp directory; no wine is started (reg_import is
replaced by a recorder).

Run:  python3 tests/test_natives_cleanup.py
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli_natives", importlib.machinery.SourceFileLoader("neutron_cli_natives", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()
DLLS = "drive_c/windows"
OVR = r"HKEY_CURRENT_USER\Software\Wine\DllOverrides"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Fake(unittest.TestCase):
    """A runtimes directory, a prefix, and reg_import replaced by a recorder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutron-natives-")
        self.runtimes = os.path.join(self.tmp, "runtimes")
        self.prefix = os.path.join(self.tmp, "Prefix")
        os.makedirs(os.path.join(self.prefix, DLLS, "system32"))
        os.makedirs(os.path.join(self.prefix, DLLS, "syswow64"))
        self.saved = (N.reg_import, N.NEUTRON_RUNTIMES_DIR)
        self.reg_calls = []
        self.reg_ok = True

        def reg_import(wine, prefix, sections, tag="neutron"):
            self.reg_calls.append(json.loads(json.dumps(sections)))
            return self.reg_ok
        N.reg_import = reg_import
        N.NEUTRON_RUNTIMES_DIR = self.runtimes

    def tearDown(self):
        N.reg_import, N.NEUTRON_RUNTIMES_DIR = self.saved
        shutil.rmtree(self.tmp)

    # -- fake runtimes ------------------------------------------------------------------------------
    def runtime(self, ver, dlls):
        """A runtime whose natives.json lists `dlls`: [(prefix_dir, dll, bytes, override dict[, requires])]."""
        root = os.path.join(self.runtimes, "neutron-wine-" + ver)
        os.makedirs(os.path.join(root, "bin"), exist_ok=True)
        wine = os.path.join(root, "bin", "wine")
        with open(wine, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(wine, 0o755)
        rows = []
        for d in dlls:
            pdir, dll, data, ovr = d[:4]
            rel = "lib/wine/%s/%s.dll" % ("x86_64-windows" if pdir == "system32" else "i386-windows", dll)
            os.makedirs(os.path.join(root, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(root, rel), "wb") as f:
                f.write(data)
            row = {"dll": dll, "file": rel, "prefix_dir": pdir, "override": ovr, "sha256": sha(data)}
            if len(d) > 4:
                row["requires"] = d[4]
            rows.append(row)
        os.makedirs(os.path.join(root, "share", "neutron"), exist_ok=True)
        with open(os.path.join(root, "share", "neutron", "natives.json"), "w") as f:
            json.dump({"format": 1, "files": rows}, f)
        return wine

    def r127(self):
        return self.runtime("11.10-127", [("system32", "d3d11", b"dxvk-127", {"d3d11": "native"}),
                                          ("system32", "d3d8", b"d3d8-64-127", {"d3d8": "native"})])

    def r128(self):
        return self.runtime("11.10-128", [("system32", "d3d11", b"dxvk-128", {"d3d11": "native"}),
                                          ("system32", "d3d8", b"d3d8-64-128", {"d3d8": "native"}),
                                          ("system32", "amfrt64", AMF_128, {"amfrt64": "native"})])

    # -- prefix helpers -----------------------------------------------------------------------------
    def path(self, rel):
        return os.path.join(self.prefix, DLLS, rel)

    def read(self, rel):
        with open(self.path(rel), "rb") as f:
            return f.read()

    def put(self, rel, data):
        with open(self.path(rel), "wb") as f:
            f.write(data)

    def record(self):
        return N.read_natives_record(self.prefix)

    def written(self):
        """The overrides the last staging wrote: {name: value}, value None = deleted."""
        return self.reg_calls[-1][OVR]

    def stage(self, wine):
        return N.stage_natives(wine, self.prefix)


AMF_128 = b"amfrt64 as 11.10-128 built it"


class Cleanup(Fake):
    def test_staging_records_every_file(self):
        step = self.stage(self.r128())
        self.assertTrue(step["ok"])
        self.assertEqual(sorted(step["staged"]), ["system32/amfrt64.dll", "system32/d3d11.dll",
                                                  "system32/d3d8.dll"])
        self.assertEqual(step["removed"], [])
        self.assertEqual(step["overrides_removed"], [])
        rec = self.record()
        self.assertEqual(rec["system32/amfrt64.dll"],
                         {"path": "system32/amfrt64.dll", "sha256": sha(AMF_128),
                          "override": {"amfrt64": "native"}})
        with open(os.path.join(self.prefix, N.NATIVES_RECORD)) as f:
            self.assertEqual(json.load(f)["runtime"], "neutron-wine-11.10-128")
        self.assertEqual(self.written()["amfrt64"], "native")

    def test_back_to_127_removes_amfrt64_and_its_override(self):
        self.stage(self.r128())
        step = self.stage(self.r127())
        self.assertTrue(step["ok"])
        self.assertEqual(step["removed"], ["system32/amfrt64.dll"])
        self.assertEqual(step["overrides_removed"], ["amfrt64"])
        self.assertFalse(os.path.exists(self.path("system32/amfrt64.dll")))
        self.assertIsNone(self.written()["amfrt64"])               # `"amfrt64"=-` in the .reg file
        self.assertEqual(self.read("system32/d3d11.dll"), b"dxvk-127")   # listed DLLs restaged
        self.assertNotIn("system32/amfrt64.dll", self.record())
        # and a second staging on 127 has nothing left to do
        step = self.stage(self.r127())
        self.assertEqual((step["removed"], step["overrides_removed"]), ([], []))
        self.assertNotIn("amfrt64", self.written())

    def test_forward_to_128_again_restages_it(self):
        self.stage(self.r128())
        self.stage(self.r127())
        step = self.stage(self.r128())
        self.assertIn("system32/amfrt64.dll", step["staged"])
        self.assertEqual(self.read("system32/amfrt64.dll"), AMF_128)
        self.assertEqual(self.written()["amfrt64"], "native")
        self.assertIn("system32/amfrt64.dll", self.record())

    def test_a_dll_the_user_replaced_is_never_deleted(self):
        self.stage(self.r128())
        self.put("system32/amfrt64.dll", b"the user's own amfrt64")
        step = self.stage(self.r127())
        self.assertEqual(self.read("system32/amfrt64.dll"), b"the user's own amfrt64")
        self.assertEqual(step["removed"], [])
        self.assertEqual(step["kept"], ["system32/amfrt64.dll"])
        self.assertIn("changed after Neutron staged it", step["detail"])
        self.assertTrue(step["ok"])
        # its override is theirs too: neither set nor deleted
        self.assertNotIn("amfrt64", self.written())
        self.assertEqual(step["overrides_removed"], [])
        # it is no longer ours: forgotten, and left alone from now on
        self.assertNotIn("system32/amfrt64.dll", self.record())
        step = self.stage(self.r127())
        self.assertEqual(self.read("system32/amfrt64.dll"), b"the user's own amfrt64")
        self.assertNotIn("kept", step)

    def test_an_override_still_listed_is_not_removed(self):
        # 128 staged d3d8 for both architectures; a runtime that keeps only the 64-bit one still wants
        # the d3d8 override, so only the file goes.
        old = self.runtime("11.10-128", [("system32", "d3d8", b"d3d8-64", {"d3d8": "native"}),
                                         ("syswow64", "d3d8", b"d3d8-32", {"d3d8": "native"})])
        self.stage(old)
        new = self.runtime("11.10-129", [("system32", "d3d8", b"d3d8-64", {"D3D8": "native"})])
        step = self.stage(new)
        self.assertEqual(step["removed"], ["syswow64/d3d8.dll"])
        self.assertEqual(step["overrides_removed"], [])
        self.assertNotIn(None, self.written().values())
        self.assertTrue(os.path.exists(self.path("system32/d3d8.dll")))

    def test_an_override_microsoft_or_provision_wants_is_not_removed(self):
        old = self.runtime("11.10-128", [("system32", "gdiplus", b"x", {"gdiplus": "native"}),
                                         ("system32", "dwrite", b"y", {"dwrite": "native"}),
                                         ("system32", "amfrt64", AMF_128, {"amfrt64": "native"})])
        self.stage(old)
        step = self.stage(self.r127())
        self.assertEqual(sorted(step["removed"]), ["system32/amfrt64.dll", "system32/dwrite.dll",
                                                   "system32/gdiplus.dll"])
        self.assertEqual(step["overrides_removed"], ["amfrt64"])   # gdiplus: Microsoft's; dwrite: the pin
        self.assertEqual(self.written()["dwrite"], "builtin")

    def test_a_recorded_file_already_gone_still_loses_its_override(self):
        self.stage(self.r128())
        os.remove(self.path("system32/amfrt64.dll"))
        step = self.stage(self.r127())
        self.assertEqual(step["removed"], [])
        self.assertEqual(step["overrides_removed"], ["amfrt64"])
        self.assertIsNone(self.written()["amfrt64"])

    def test_a_failed_registry_write_is_retried_next_time(self):
        self.stage(self.r128())
        self.reg_ok = False
        step = self.stage(self.r127())
        self.assertFalse(os.path.exists(self.path("system32/amfrt64.dll")))
        self.assertEqual(step["overrides_removed"], [])
        self.assertIn("system32/amfrt64.dll", self.record())       # still owed an override removal
        self.reg_ok = True
        step = self.stage(self.r127())
        self.assertEqual(step["overrides_removed"], ["amfrt64"])
        self.assertNotIn("system32/amfrt64.dll", self.record())

    def test_a_row_waiting_for_its_requirement_keeps_its_record(self):
        shim = ("system32", "ucrtbase", b"shim", {"*ucrtbase": "native,builtin"},
                {"file": "ucrtbase_orig.dll", "sha256": sha(b"microsoft ucrt")})
        self.put("system32/ucrtbase_orig.dll", b"microsoft ucrt")
        self.stage(self.runtime("11.10-128", [shim]))
        self.assertIn("system32/ucrtbase.dll", self.record())
        os.remove(self.path("system32/ucrtbase_orig.dll"))
        step = self.stage(self.runtime("11.10-129", [shim]))
        self.assertFalse(step["ok"])                               # unchanged: "not staged: ..."
        self.assertEqual(step["removed"], [])
        self.assertTrue(os.path.exists(self.path("system32/ucrtbase.dll")))
        self.assertIn("system32/ucrtbase.dll", self.record())

    def test_a_record_naming_a_path_outside_the_prefix_is_ignored(self):
        outside = os.path.join(self.tmp, "outside.dll")
        with open(outside, "wb") as f:
            f.write(b"not Neutron's")
        with open(os.path.join(self.prefix, N.NATIVES_RECORD), "w") as f:
            json.dump({"format": 1, "files": [
                {"path": "../../../outside.dll", "sha256": sha(b"not Neutron's"), "override": {}},
                {"path": "/etc/passwd", "sha256": "0" * 64, "override": {}}]}, f)
        self.stage(self.r127())
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(self.record().keys(), {"system32/d3d11.dll", "system32/d3d8.dll"})


class NoRecord(Fake):
    """Prefixes provisioned by CLI 1.0.0-beta.13 or older: no record, so only the known amfrt64."""

    def test_exactly_128s_amfrt64_is_removed(self):
        self.r128()                                                # installed, so its checksum is known
        self.put("system32/amfrt64.dll", AMF_128)
        step = self.stage(self.r127())
        self.assertEqual(step["removed"], ["system32/amfrt64.dll"])
        self.assertEqual(step["overrides_removed"], ["amfrt64"])
        self.assertFalse(os.path.exists(self.path("system32/amfrt64.dll")))

    def test_a_different_amfrt64_is_left_alone(self):
        self.r128()
        self.put("system32/amfrt64.dll", b"some other amfrt64")
        step = self.stage(self.r127())
        self.assertEqual(self.read("system32/amfrt64.dll"), b"some other amfrt64")
        self.assertEqual((step["removed"], step["overrides_removed"]), ([], []))
        self.assertNotIn("kept", step)                             # never ours, nothing to report
        self.assertNotIn("amfrt64", self.written())

    def test_without_128_installed_it_is_left_alone(self):
        self.put("system32/amfrt64.dll", AMF_128)
        step = self.stage(self.r127())
        self.assertTrue(os.path.exists(self.path("system32/amfrt64.dll")))
        self.assertEqual((step["removed"], step["overrides_removed"]), ([], []))

    def test_no_file_means_no_override_change(self):
        self.r128()
        step = self.stage(self.r127())
        self.assertEqual((step["removed"], step["overrides_removed"]), ([], []))
        self.assertNotIn("amfrt64", self.written())

    def test_other_unlisted_dlls_are_never_touched(self):
        self.r128()
        self.put("system32/d3d12.dll", b"left by an older runtime, unrecorded")
        self.stage(self.r127())
        self.assertTrue(os.path.exists(self.path("system32/d3d12.dll")))


class PrefixesBehind(unittest.TestCase):
    """`neutron update`'s closing hint names prefixes on a runtime other than the one it installed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutron-behind-")
        self.saved = (N.NEUTRON_RUNTIMES_DIR, N.neutron_prefixes, os.environ.pop("NEUTRON_WINE_VERSION", None))
        N.NEUTRON_RUNTIMES_DIR = os.path.join(self.tmp, "runtimes")
        for ver, stamp in (("11.10-127", 1_700_000_127), ("11.10-128", 1_700_000_128)):
            root = os.path.join(N.NEUTRON_RUNTIMES_DIR, "neutron-wine-" + ver)
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "share", "wine"))
            with open(os.path.join(root, "bin", "wine"), "w") as f:
                f.write("#!/bin/sh\n")
            inf = os.path.join(root, "share", "wine", "wine.inf")
            open(inf, "w").close()
            os.utime(inf, (stamp, stamp))
        self.p = os.path.join(self.tmp, "Adobe")
        os.makedirs(os.path.join(self.p, "drive_c"))
        N.neutron_prefixes = lambda: [self.p]

    def tearDown(self):
        N.NEUTRON_RUNTIMES_DIR, N.neutron_prefixes, env = self.saved
        if env is not None:
            os.environ["NEUTRON_WINE_VERSION"] = env
        shutil.rmtree(self.tmp)

    def on(self, ver):
        with open(os.path.join(self.p, ".update-timestamp"), "w") as f:
            f.write("1700000%s\r\n" % ver[-3:])

    def test_back_from_a_pre_release_says_nothing_about_it(self):
        # update installed the Latest 127 and moved the prefix there; 128 is still installed and newer
        self.on("11.10-127")
        self.assertEqual(N._prefixes_behind("11.10-127"), [])

    def test_a_prefix_left_on_the_pre_release_is_pointed_back_with_a_pinned_command(self):
        self.on("11.10-128")                                       # skipped: an app was running
        p, = N._prefixes_behind("11.10-127")
        self.assertEqual((p["runtime"], p["latest"]), ("11.10-128", "11.10-127"))
        self.assertEqual(p["command"], "NEUTRON_WINE_VERSION=11.10-127 neutron prefix provision " + self.p)

    def test_the_normal_case_is_unchanged(self):
        # update installed 128, the newest: a prefix left on 127 gets the plain command as before
        self.on("11.10-127")
        p, = N._prefixes_behind("11.10-128")
        self.assertEqual(p, {"prefix": self.p, "runtime": "11.10-127", "latest": "11.10-128",
                             "command": "neutron prefix provision " + self.p})
        self.assertEqual(N._prefixes_behind(), [p])                # no version: the newest installed

    def test_a_version_that_is_not_installed_falls_back_to_the_default(self):
        self.on("11.10-127")
        p, = N._prefixes_behind("11.10-200")
        self.assertEqual(p["latest"], "11.10-128")


if __name__ == "__main__":
    unittest.main()
