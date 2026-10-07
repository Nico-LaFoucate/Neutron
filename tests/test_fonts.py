#!/usr/bin/env python3
"""Tests for `neutron fonts check` (bin/neutron: fonts_verdict and the checks under it).

Every test here is validated against a KNOWN-BAD state as well as a good one. The reason is on
record: `doctor` once returned healthy on a build we knew was broken, and the first version of
the Roman-default check condemned the healthy dev-box prefix. A check that has never seen a
broken prefix is not a check (wiki INCIDENTS.md 2026-08-11 / 2026-08-25).

The prefixes are synthetic and hermetic: a minimal TrueType `name` table is generated in-process
with whatever PostScript name a test needs, so nothing here depends on the host's fonts, a
runtime, or wine. `fonts_verdict` never starts wine, which is what makes that possible.

Run:  python3 tests/test_fonts.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import struct
import sys
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

# Wine's substitutes carry exactly these PostScript names (read from the 11.10-85 runtime's
# share/wine/fonts with font_postscript_names on 2026-09-13).
WINE_PS = {"times.ttf": "WineTimesNewRoman", "arial.ttf": "WineArial", "cour.ttf": "WineCourierNew"}


def make_ttf(ps_name, mac_record=False, family=None):
    """A minimal sfnt with only a `name` table: enough for the name-table readers.

    mac_record=True adds a Macintosh-platform nameID 6 record whose bytes are UTF-16 (the shape
    the genuine Microsoft core fonts have), so the parser's two-record handling is exercised.
    family adds a nameID 1 record -- what a replacement TARGET is verified by."""
    recs = []
    if mac_record:
        recs.append((1, 0, 0, 6, ps_name.encode("utf-16-be")))
    if family:
        recs.append((3, 1, 0x409, 1, family.encode("utf-16-be")))
    recs.append((3, 1, 0x409, 6, ps_name.encode("utf-16-be")))
    strings = b"".join(r[4] for r in recs)
    name = struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs))
    off = 0
    for pid, eid, lid, nid, raw in recs:
        name += struct.pack(">HHHHHH", pid, eid, lid, nid, len(raw), off)
        off += len(raw)
    name += strings
    header = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    table = b"name" + struct.pack(">III", 0, 12 + 16, len(name))
    return header + table + name


def cache_record(font_name, family, style, length=330412):
    return ("%BeginFont\nHandler:WinTTHandler\nFontType:TrueType\nFontName:{f}\nFamilyName:{fam}\n"
            "StyleName:{s}\nMenuName:{fam}\nWritingScript:Roman\nFileLength:{n}\n%EndFont\n"
            ).format(f=font_name, fam=family, s=style, n=length)


# The map a prefix on THIS machine is expected to carry (runtime fonts.json when present).
EXPECTED_MAP = N.expected_font_replacements(N.resolve_runtime())


class Prefix:
    """A throwaway synthetic prefix: windows/Fonts, a user dir, system.reg and user.reg."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="neutron-fonts-test-")
        self.fonts = os.path.join(self.root, "drive_c", "windows", "Fonts")
        os.makedirs(self.fonts)
        self.cache_dir = os.path.join(self.root, "drive_c", "users", "tester", "AppData", "Local",
                                      "Temp", "Adobe", "After Effects", "25.3", "Typesupport")
        os.makedirs(self.cache_dir)
        self.registered = []
        self.replacements = dict(EXPECTED_MAP)
        self.write_reg()

    def font(self, filename, ps_name, mac_record=False, register=True, family=None):
        with open(os.path.join(self.fonts, filename), "wb") as f:
            f.write(make_ttf(ps_name, mac_record, family))
        if register:
            self.registered.append(filename)
            self.write_reg()

    def write_reg(self):
        lines = ["WINE REGISTRY Version 2", ";; All keys relative to \\\\Machine", "",
                 "[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts] 1789168449",
                 "#time=1dd42433fd724f6"]
        for fn in self.registered:
            stem = os.path.splitext(fn)[0]
            lines.append('"%s (TrueType)"="%s"' % (stem, fn))
        # a host font registered by full DOS path, as register_prefix_fonts() writes them
        lines.append('"@Noto Sans CJK HK (TrueType)"="Z:\\\\usr\\\\share\\\\fonts\\\\noto-cjk\\\\NotoSansCJK-Regular.ttc"')
        lines += ["", "[Software\\\\Wine\\\\Fonts] 1789168449", '"Something"="else"', ""]
        with open(os.path.join(self.root, "system.reg"), "w") as f:
            f.write("\n".join(lines))
        ulines = ["WINE REGISTRY Version 2", ";; All keys relative to \\\\User\\\\S-1-5-21-0-0-0-1000", "",
                  "[Software\\\\Wine\\\\Drivers] 1789168449", '"Graphics"="wayland"', ""]
        if self.replacements is not None:
            ulines += ["[Software\\\\Wine\\\\Fonts\\\\Replacements] 1789168449", "#time=1dd3be727dfa524"]
            ulines += ['"%s"="%s"' % (k, v) for k, v in self.replacements.items()]
            ulines.append("")
        ulines += ["[Software\\\\Wine\\\\Fonts] 1789168449", '"Unrelated"="value"', ""]
        with open(os.path.join(self.root, "user.reg"), "w") as f:
            f.write("\n".join(ulines))

    def cache(self, *records):
        with open(os.path.join(self.cache_dir, "AdobeFnt_OSFonts.lst"), "w") as f:
            f.write("%!Adobe-FontList 1.25\n%Locale:0x409\n\n" + "".join(records))

    def genuine_roman(self):
        self.font("times.ttf", "TimesNewRomanPSMT", mac_record=True)
        self.font("arial.ttf", "ArialMT", mac_record=True)
        self.font("cour.ttf", "CourierNewPSMT", mac_record=True)

    def wine_roman(self):
        for fn, ps in WINE_PS.items():
            self.font(fn, ps)

    def core_six(self):
        for n in N._MS_CORE_FONTS:
            self.font(n + ".ttf", n.capitalize())

    def adobe_clean(self, register=True):
        self.font("AdobeClean-Regular.otf", "AdobeClean-Regular", register=register, family="Adobe Clean")

    def healthy(self):
        self.genuine_roman()
        self.core_six()
        self.adobe_clean()

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def by_name(verdict):
    return {c["name"]: c for c in verdict["checks"]}


class FontsVerdict(unittest.TestCase):
    def setUp(self):
        self.p = Prefix()
        self.addCleanup(self.p.cleanup)

    # --- the synthetic font is a faithful stand-in ------------------------------------------
    def test_postscript_parser_reads_both_records(self):
        """Genuine MS fonts carry a Mac-platform nameID 6 whose bytes are UTF-16 and a Windows
        one; the first parser returned only the first record and condemned the healthy prefix."""
        self.p.font("times.ttf", "TimesNewRomanPSMT", mac_record=True)
        names = N.font_postscript_names(os.path.join(self.p.fonts, "times.ttf"))
        self.assertIn("TimesNewRomanPSMT", names)
        self.p.font("arial.ttf", "WineArial")
        self.assertIn("WineArial", N.font_postscript_names(os.path.join(self.p.fonts, "arial.ttf")))

    # --- healthy ---------------------------------------------------------------------------
    def test_healthy_prefix_is_good_with_nothing_to_repair(self):
        self.p.healthy()
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(v["status"], "good", v)
        self.assertEqual(v["repair"], [])
        self.assertTrue(all(c["status"] == "good" for c in v["checks"]), v["checks"])
        self.assertIn("Fonts are good", v["summary"])

    # --- the After Effects fault: Roman defaults by PostScript name -------------------------
    def test_all_three_wine_substitutes_is_bad(self):
        """The files exist under the real Microsoft filenames. A presence check passes; this
        must not."""
        self.p.wine_roman()
        self.p.core_six()
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(v["status"], "bad")
        self.assertEqual(by_name(v)["roman-default"]["status"], "bad")
        self.assertIn("After Effects will not start", v["summary"])
        self.assertIn("restore a genuine Times New Roman / Arial / Courier New", v["repair"])
        states = {f["file"]: f["state"] for f in by_name(v)["roman-default"]["files"]}
        self.assertEqual(states, {"times.ttf": "wine-substitute", "arial.ttf": "wine-substitute",
                                  "cour.ttf": "wine-substitute"})

    def test_missing_roman_files_is_bad(self):
        self.p.core_six()
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(by_name(v)["roman-default"]["status"], "bad")
        self.assertEqual(v["status"], "bad")

    def test_one_genuine_face_is_enough(self):
        """CoolType falls back. An earlier version failed on any fake and told a user to delete
        a correct cache -- the false PASS, mirrored. Do not regress it."""
        self.p.font("times.ttf", "WineTimesNewRoman")
        self.p.font("arial.ttf", "ArialMT", mac_record=True)
        self.p.font("cour.ttf", "WineCourierNew")
        self.p.core_six()
        self.p.adobe_clean()
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(by_name(v)["roman-default"]["status"], "good", v)
        self.assertEqual(v["status"], "good", v)

    # --- the build tester's three days: genuine files, stale cache -------------------------
    def test_stale_cache_over_genuine_files_is_bad_and_invalidation_fixes_it(self):
        self.p.healthy()
        self.p.cache(cache_record("WineTimesNewRoman", "Times New Roman", "Regular", 147172),
                     cache_record("TimesNewRomanPS-BoldMT", "Times New Roman", "Bold"),
                     cache_record("WineArial", "Arial", "Regular", 134188),
                     cache_record("WineCourierNew", "Courier New", "Regular", 143264))
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(v["status"], "bad", v)
        self.assertEqual(by_name(v)["roman-default"]["status"], "good")   # the files ARE fine
        self.assertEqual(by_name(v)["cooltype-cache"]["status"], "bad")
        self.assertIn("cache", v["summary"])
        self.assertIn("delete CoolType's stale font cache (Adobe rebuilds it)", v["repair"])
        # the repair primitive, then the same check must pass -- both directions
        self.assertEqual(N.invalidate_cooltype_caches(self.p.root), 1)
        v2 = N.fonts_verdict(self.p.root)
        self.assertEqual(v2["status"], "good", v2)

    def test_faithful_cache_is_good(self):
        self.p.healthy()
        self.p.cache(cache_record("TimesNewRomanPSMT", "Times New Roman", "Regular"),
                     cache_record("ArialMT", "Arial", "Regular"),
                     cache_record("CourierNewPSMT", "Courier New", "Regular"))
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(by_name(v)["cooltype-cache"]["status"], "good", v)
        self.assertEqual(v["status"], "good")

    def test_cjk_wine_records_are_not_blamed(self):
        """Every real prefix carries WineYahei / WineTahoma / WineSymbol records. A lookup that
        searched the whole file for FontName:Wine* blamed a CJK face for the Roman default."""
        self.p.healthy()
        self.p.cache(cache_record("WineYahei", "Microsoft YaHei", "Regular"),
                     cache_record("WineTahoma", "Tahoma", "Regular"),
                     cache_record("TimesNewRomanPSMT", "Times New Roman", "Regular"),
                     cache_record("WineArial", "Arial", "Regular", 134188))
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(by_name(v)["cooltype-cache"]["status"], "good", v)

    # --- the video trio: the six names Wine ships nothing under ----------------------------
    def test_missing_core_fonts_is_bad(self):
        self.p.genuine_roman()
        v = N.fonts_verdict(self.p.root)
        c = by_name(v)["ms-core-fonts"]
        self.assertEqual(c["status"], "bad")
        self.assertEqual(c["missing"], list(N._MS_CORE_FONTS))
        self.assertEqual(v["status"], "bad")
        self.assertIn("Premiere, After Effects and Media Encoder", v["summary"])
        self.assertIn("install the Microsoft core fonts", v["repair"])

    def test_partial_core_fonts_names_the_missing_ones(self):
        self.p.genuine_roman()
        self.p.core_six()
        os.remove(os.path.join(self.p.fonts, "comic.ttf"))
        c = by_name(N.fonts_verdict(self.p.root))["ms-core-fonts"]
        self.assertEqual(c["status"], "bad")
        self.assertEqual(c["missing"], ["comic"])
        self.assertIn("comic", c["detail"])

    def test_core_font_check_is_blind_to_faked_roman_by_design(self):
        """Documented limitation: 6/6 says nothing about times/arial/cour. The roman-default
        check must be the one that fails here, and the verdict as a whole must still be bad."""
        self.p.wine_roman()
        self.p.core_six()
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(by_name(v)["ms-core-fonts"]["status"], "good")
        self.assertEqual(by_name(v)["roman-default"]["status"], "bad")
        self.assertEqual(v["status"], "bad")

    # --- registration: a font the prefix merely HAS is invisible to the apps ---------------
    def test_registered_values_are_read_by_basename_from_system_reg(self):
        self.p.healthy()
        names = N._registered_font_basenames(self.p.root)
        self.assertIn("times.ttf", names)
        self.assertIn("georgia.ttf", names)
        self.assertIn("notosanscjk-regular.ttc", names)     # full DOS path -> basename
        self.assertNotIn("something", names)                 # values outside the Fonts key

    def test_unregistered_hand_copied_font_is_warn_not_bad(self):
        """The user story: a font copied into windows/Fonts by hand and never registered.
        The apps start, so this is amber, and Repair is offered."""
        self.p.healthy()
        self.p.font("BebasNeue-Regular.ttf", "BebasNeue-Regular", register=False)
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(v["status"], "warn", v)
        c = by_name(v)["registered"]
        self.assertEqual(c["status"], "warn")
        self.assertEqual(c["files"], ["BebasNeue-Regular.ttf"])
        self.assertIn("not registered", v["summary"])
        self.assertIn("register 1 font file with Wine", v["repair"])
        # registering it (what repair does) turns the same check green
        self.p.registered.append("BebasNeue-Regular.ttf")
        self.p.write_reg()
        self.assertEqual(N.fonts_verdict(self.p.root)["status"], "good")

    def test_unregistered_adobe_clean_is_bad(self):
        """Copied-but-unregistered Adobe Clean is the blank Photoshop menu bar."""
        self.p.genuine_roman(); self.p.core_six()
        self.p.font("AdobeClean-Regular.otf", "AdobeClean-Regular", register=False, family="Adobe Clean")
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(v["status"], "bad")
        self.assertEqual(by_name(v)["registered"]["status"], "bad")
        # an unregistered target is ALSO a broken map: the redirect points at nothing dwrite has
        self.assertEqual(by_name(v)["replacements"]["status"], "bad")
        self.assertIn("Photoshop", v["summary"])

    def test_non_font_files_in_fonts_dir_are_ignored(self):
        self.p.healthy()
        with open(os.path.join(self.p.fonts, "desktop.ini"), "w") as f:
            f.write("x")
        self.assertEqual(N.fonts_verdict(self.p.root)["status"], "good")

    def test_unreadable_system_reg_is_warn_not_a_crash(self):
        self.p.healthy()
        os.remove(os.path.join(self.p.root, "system.reg"))
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(by_name(v)["registered"]["status"], "warn")
        self.assertEqual(v["status"], "warn")

    # --- the replacement map: Segoe UI and friends -> Adobe Clean -----------------------------
    def test_replacement_map_intact_is_good(self):
        self.p.healthy()
        c = by_name(N.fonts_verdict(self.p.root))["replacements"]
        self.assertEqual(c["status"], "good", c)
        self.assertIn("Adobe Clean", c["detail"])
        self.assertIn("AdobeClean-Regular.otf", c["detail"])

    def test_missing_replacement_entries_is_bad(self):
        """The Photoshop startup deadlock: Adobe asks dwrite for Segoe UI, nothing answers."""
        self.p.healthy()
        for k in ("Segoe UI", "Calibri", "Noto Sans JP"):
            del self.p.replacements[k]
        self.p.write_reg()
        v = N.fonts_verdict(self.p.root)
        c = by_name(v)["replacements"]
        self.assertEqual(c["status"], "bad", c)
        self.assertEqual(sorted(c["missing"]), ["Calibri", "Noto Sans JP", "Segoe UI"])
        self.assertEqual(v["status"], "bad")
        self.assertIn("Photoshop will deadlock at startup", v["summary"])
        self.assertIn("missing 3 of %d" % len(EXPECTED_MAP), v["summary"])
        self.assertIn("restore 3 font replacement entries", v["repair"])
        # restoring them (what repair does) turns the same check green
        self.p.replacements = dict(EXPECTED_MAP); self.p.write_reg()
        self.assertEqual(by_name(N.fonts_verdict(self.p.root))["replacements"]["status"], "good")

    def test_no_replacement_key_at_all_is_bad(self):
        """A fresh wineboot prefix, or a wiped user.reg section: every entry missing."""
        self.p.healthy()
        self.p.replacements = None; self.p.write_reg()
        c = by_name(N.fonts_verdict(self.p.root))["replacements"]
        self.assertEqual(c["status"], "bad")
        self.assertEqual(len(c["missing"]), len(EXPECTED_MAP))

    def test_replacement_target_absent_is_bad(self):
        """Entries intact, but Adobe Clean is not in the prefix: the same failure, one step later."""
        self.p.genuine_roman(); self.p.core_six()          # no Adobe Clean at all
        v = N.fonts_verdict(self.p.root)
        c = by_name(v)["replacements"]
        self.assertEqual(c["status"], "bad", c)
        self.assertEqual(c["missing"], [])
        self.assertEqual(c["absent_targets"], ["Adobe Clean"])
        self.assertIn("points at Adobe Clean, which is not in this prefix", v["summary"])
        # a registered file with the family name in nameID 16 only (a Black/Bold face) satisfies it
        self.p.font("AdobeCleanBlack.otf", "AdobeClean-Black", family=None)      # registers it
        with open(os.path.join(self.p.fonts, "AdobeCleanBlack.otf"), "wb") as f:  # nameID 16 only
            f.write(make_ttf("AdobeClean-Black", family="Adobe Clean")
                    .replace(struct.pack(">HHHH", 3, 1, 0x409, 1), struct.pack(">HHHH", 3, 1, 0x409, 16)))
        self.assertEqual(by_name(N.fonts_verdict(self.p.root))["replacements"]["status"], "good")

    def test_replacement_pointing_elsewhere_is_warn(self):
        """A customized redirect to a family that exists: the apps start, so amber."""
        self.p.healthy()
        self.p.font("MyriadPro-Regular.otf", "MyriadPro-Regular", family="Myriad Pro")
        self.p.replacements["Segoe UI"] = "Myriad Pro"; self.p.write_reg()
        v = N.fonts_verdict(self.p.root)
        c = by_name(v)["replacements"]
        self.assertEqual(c["status"], "warn", c)
        self.assertEqual(c["differ"], {"Segoe UI": "Myriad Pro"})
        self.assertEqual(v["status"], "warn")
        self.assertIn("restore 1 font replacement entries", v["repair"])

    def test_reg_section_reader_unescapes_and_scopes(self):
        self.p.healthy()
        vals = N._reg_section_values(os.path.join(self.p.root, "user.reg"), r"Software\Wine\Fonts\Replacements")
        self.assertEqual(vals, EXPECTED_MAP)
        self.assertEqual(N._reg_section_values(os.path.join(self.p.root, "user.reg"), r"Software\Wine\Fonts"),
                         {"Unrelated": "value"})
        self.assertEqual(N._reg_section_values(os.path.join(self.p.root, "user.reg"), r"Software\Nope"), {})
        self.assertIsNone(N._reg_section_values(os.path.join(self.p.root, "nope.reg"), "x"))
        self.assertEqual(N._reg_unescape(r'Z:\\usr\\share \"q\"'), r'Z:\usr\share "q"')

    def test_expected_map_is_the_provision_map(self):
        """One definition: whatever provision writes is what check verifies."""
        self.assertEqual(N.expected_font_replacements(None), N.PROVISION_FONT_REPLACEMENTS)
        self.assertGreaterEqual(len(EXPECTED_MAP), 16)
        self.assertTrue(all(v == "Adobe Clean" for v in EXPECTED_MAP.values()), EXPECTED_MAP)

    # --- the summary leads with the startup failure, not the first check --------------------
    def test_summary_priority(self):
        self.p.wine_roman()                                   # bad
        self.p.font("Extra.ttf", "Extra", register=False)     # warn
        v = N.fonts_verdict(self.p.root)
        self.assertEqual(v["status"], "bad")
        self.assertIn("After Effects will not start", v["summary"])

    def test_verdict_shape_is_stable_for_collider(self):
        self.p.healthy()
        v = N.fonts_verdict(self.p.root)
        for key in ("status", "summary", "checks", "repair", "apps_running"):
            self.assertIn(key, v)
        self.assertEqual([c["name"] for c in v["checks"]],
                         ["roman-default", "cooltype-cache", "ms-core-fonts", "replacements", "registered"])
        for c in v["checks"]:
            self.assertIn(c["status"], ("good", "warn", "bad"))
            self.assertTrue(c["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
