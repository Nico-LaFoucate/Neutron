#!/usr/bin/env python3
"""Tests for the icon-font map: "Segoe MDL2 Assets" -> "Neutron Icons"
(bin/neutron: expected_icon_font_replacements, the `icon-font` row of fonts_verdict, and what
repair_prefix_fonts writes).

Topaz Photo draws its minimize/maximize/restore/close buttons as text in "Segoe MDL2 Assets"
(U+E921/E922/E923/E8BB). Microsoft's font is not redistributable; the runtime ships our own
"Neutron Icons" in its Wine fonts dir and the prefix's Replacements map points that name at it
("Segoe Fluent Icons" is deliberately not mapped).
Every state is checked against a KNOWN-BAD one too (unmapped, mapped-but-unregistered): a check
that has never seen a broken prefix is not a check (wiki INCIDENTS.md 2026-08-11 / 2026-08-25).

Hermetic: synthetic runtime (bin/wine + share/wine/fonts) and prefix (user.reg, system.reg),
fonts carry only a `name` table; resolve_wine is pointed at the synthetic runtime; never runs wine.

Run:  python3 tests/test_icon_font.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import struct
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()
MDL2, FLUENT, OURS = "Segoe MDL2 Assets", "Segoe Fluent Icons", "Neutron Icons"


def make_ttf(family, ps_name):
    """A minimal sfnt with only a `name` table carrying family (nameID 1) and PostScript name (6)."""
    recs = [(3, 1, 0x409, 1, family.encode("utf-16-be")), (3, 1, 0x409, 6, ps_name.encode("utf-16-be"))]
    name = struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs))
    off = 0
    for pid, eid, lid, nid, raw in recs:
        name += struct.pack(">HHHHHH", pid, eid, lid, nid, len(raw), off)
        off += len(raw)
    name += b"".join(r[4] for r in recs)
    head = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    return head + struct.pack(">4sIII", b"name", 0, 12 + 16, len(name)) + name


def _reg_escape(s):
    return s.replace("\\", "\\\\")


class IconFontTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutron-iconfont-")
        self.rt = os.path.join(self.tmp, "runtime")
        self.fonts = os.path.join(self.rt, "share", "wine", "fonts")
        os.makedirs(os.path.join(self.rt, "bin"))
        os.makedirs(self.fonts)
        self.wine = os.path.join(self.rt, "bin", "wine")
        with open(self.wine, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.wine, 0o755)
        with open(os.path.join(self.fonts, "tahoma.ttf"), "wb") as f:
            f.write(make_ttf("Tahoma", "Tahoma"))
        self.prefix = os.path.join(self.tmp, "prefix")
        os.makedirs(os.path.join(self.prefix, "drive_c", "windows", "Fonts"))
        self._saved = N.resolve_wine
        N.resolve_wine = lambda: (self.wine, True)

    def tearDown(self):
        N.resolve_wine = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ship_font(self):
        p = os.path.join(self.fonts, N.ICON_FONT_FILE)
        with open(p, "wb") as f:
            f.write(make_ttf(OURS, "NeutronIcons-Regular"))
        return p

    def write_prefix(self, replacements, registered):
        with open(os.path.join(self.prefix, "user.reg"), "w") as f:
            f.write("WINE REGISTRY Version 2\n;; All keys relative to \\\\User\\\\S-1-5-21-0-0-0-1000\n\n")
            f.write("[Software\\\\Wine\\\\Fonts\\\\Replacements] 1762400000\n")
            for k, v in replacements.items():
                f.write('"%s"="%s"\n' % (k, v))
        with open(os.path.join(self.prefix, "system.reg"), "w") as f:
            f.write("WINE REGISTRY Version 2\n;; All keys relative to \\\\Machine\n\n")
            f.write("[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts] 1762400000\n")
            for name, path in registered.items():
                f.write('"%s"="%s"\n' % (name, _reg_escape("Z:" + path.replace("/", "\\"))))

    def row(self):
        v = N.fonts_verdict(self.prefix)
        return v, next(c for c in v["checks"] if c["name"] == "icon-font")

    def test_runtime_without_the_font_expects_nothing(self):
        self.assertEqual(N.expected_icon_font_replacements(self.wine), {})
        self.write_prefix({}, {})
        _v, row = self.row()
        self.assertEqual(row["status"], "good")
        self.assertIn("ships no icon font", row["detail"])

    def test_runtime_with_the_font_expects_mdl2_only(self):
        self.ship_font()
        self.assertEqual(N.expected_icon_font_replacements(self.wine), {MDL2: OURS})
        self.assertNotIn(FLUENT, N.expected_icon_font_replacements(self.wine))

    def test_unmapped_prefix_is_warn_and_repair_maps_it(self):         # KNOWN-BAD
        p = self.ship_font()
        self.write_prefix({}, {"Neutron Icons (TrueType)": p})
        v, row = self.row()
        self.assertEqual(row["status"], "warn")
        self.assertEqual(row["missing"], [MDL2])
        self.assertIn("map %s to %s" % (MDL2, OURS), v["repair"])

    def test_map_to_another_family_is_warn(self):                    # KNOWN-BAD
        p = self.ship_font()
        self.write_prefix({MDL2: "Some Other Font"}, {"Neutron Icons (TrueType)": p})
        _v, row = self.row()
        self.assertEqual(row["status"], "warn")
        self.assertEqual(row["missing"], [MDL2])

    def test_mapped_but_unregistered_is_warn(self):                  # KNOWN-BAD
        self.ship_font()
        self.write_prefix({MDL2: OURS}, {})
        v, row = self.row()
        self.assertEqual(row["status"], "warn")
        self.assertIn("not registered", row["detail"])
        self.assertIn("register %s" % OURS, v["repair"])

    def test_mapped_and_registered_is_good(self):
        p = self.ship_font()
        self.write_prefix({MDL2: OURS}, {"Neutron Icons (TrueType)": p})
        v, row = self.row()
        self.assertEqual(row["status"], "good", row["detail"])
        self.assertIn(N.ICON_FONT_FILE, row["detail"])
        self.assertFalse([r for r in v["repair"] if OURS in r])

    def test_icon_entries_leave_the_adobe_map_check_alone(self):
        p = self.ship_font()
        self.write_prefix({}, {"Neutron Icons (TrueType)": p})
        rep_without = next(c for c in N.fonts_verdict(self.prefix)["checks"] if c["name"] == "replacements")
        self.write_prefix({MDL2: OURS}, {"Neutron Icons (TrueType)": p})
        rep_with = next(c for c in N.fonts_verdict(self.prefix)["checks"] if c["name"] == "replacements")
        self.assertEqual(rep_without["status"], rep_with["status"])
        self.assertEqual(rep_with.get("differ"), rep_without.get("differ"))

    def repair(self, replacements, registered):
        """repair_prefix_fonts on a prefix holding `replacements`/`registered`, every other step stubbed; reg_set lands
        its value in user.reg, as the registry reaching disk would. Returns (result, the Replacements writes)."""
        from unittest import mock
        have, writes = dict(replacements), []
        self.write_prefix(have, registered)

        def reg_set(_wine, _prefix, key, name, _vtype, data):
            writes.append((key, name, data))
            have[name] = data
            self.write_prefix(have, registered)
        with mock.patch.object(N, "_repair_roman_defaults", return_value=([], [], False)), \
             mock.patch.object(N, "_ms_core_fonts_status", return_value=([], [])), \
             mock.patch.object(N, "expected_font_replacements", return_value={}), \
             mock.patch.object(N, "CJK_FONT_REPLACEMENTS", {}, create=True), \
             mock.patch.object(N, "reg_set", side_effect=reg_set), \
             mock.patch.object(N, "seed_adobe_clean", return_value={"ok": True}), \
             mock.patch.object(N, "register_prefix_fonts", return_value=1), \
             mock.patch.object(N, "registry_to_disk", return_value=True), \
             mock.patch.object(N, "invalidate_cooltype_caches", return_value=0):
            res = N.repair_prefix_fonts(self.wine, self.prefix)
        return res, [w for w in writes if w[0] == r"HKCU\Software\Wine\Fonts\Replacements"]

    @staticmethod
    def icon_step(res):
        return next(s for s in res["steps"] if s["step"] == "icon_font_replacements")

    def test_repair_maps_an_unmapped_prefix(self):                    # KNOWN-BAD -> good
        p = self.ship_font()
        res, writes = self.repair({}, {"Neutron Icons (TrueType)": p})
        self.assertEqual(writes, [(r"HKCU\Software\Wine\Fonts\Replacements", MDL2, OURS)])
        self.assertEqual(self.icon_step(res)["restored"], [MDL2])
        self.assertTrue(self.icon_step(res)["ok"], self.icon_step(res))
        self.assertEqual(next(c for c in res["before"]["checks"] if c["name"] == "icon-font")["status"], "warn")
        self.assertEqual(next(c for c in res["after"]["checks"] if c["name"] == "icon-font")["status"], "good")

    def test_repair_leaves_a_mapped_prefix_alone(self):
        p = self.ship_font()
        res, writes = self.repair({MDL2: OURS}, {"Neutron Icons (TrueType)": p})
        self.assertEqual(writes, [])
        self.assertTrue(self.icon_step(res)["ok"])

    def test_repair_maps_nothing_on_a_runtime_without_the_font(self):
        res, writes = self.repair({}, {})
        self.assertEqual(writes, [])
        self.assertTrue(self.icon_step(res)["ok"])
        self.assertIn("ships no icon font", self.icon_step(res)["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
