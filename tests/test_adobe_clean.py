#!/usr/bin/env python3
"""Tests for copying Adobe Clean into windows/Fonts (bin/neutron: seed_adobe_clean).

The font replacement map sends Segoe UI and others to Adobe Clean, so Adobe Clean has to be in
windows/Fonts and registered. Every Adobe app ships it in its own folder, but only Photoshop's
copy used to be seeded (by Mud Hut, for downloads). A prefix with only Lightroom Classic, copied
from a Windows drive or downloaded, failed the fonts check, and Repair could not fix it
("still broken after repair", GitHub issue Neutron#2). Provision and Repair now copy it in from
whichever app is installed.

The font files here are generated: a sfnt with nothing but a `name` table, which is all the
CLI's name reader looks at. Adobe's own fonts are not redistributable.

Run:  python3 tests/test_adobe_clean.py
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


def make_font(path, family):
    """A minimal TrueType file whose only table is `name`, with nameID 1 = `family`."""
    s = family.encode("utf-16-be")
    name = struct.pack(">HHH", 0, 1, 18) + struct.pack(">HHHHHH", 3, 1, 0x409, 1, len(s), 0) + s
    head = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    rec = b"name" + struct.pack(">III", 0, 12 + 16, len(name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(head + rec + name)


class SeedAdobeClean(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp(prefix="neutron-adobeclean-")
        self.adobe = os.path.join(self.prefix, "drive_c", "Program Files", "Adobe")
        self.fonts = os.path.join(self.prefix, "drive_c", "windows", "Fonts")
        os.makedirs(self.fonts)

    def tearDown(self):
        shutil.rmtree(self.prefix, ignore_errors=True)

    def test_generated_font_reads_back(self):
        p = os.path.join(self.prefix, "x.ttf")
        make_font(p, "Adobe Clean")
        self.assertIn("Adobe Clean", N.font_family_names(p))

    def test_lightroom_classic_only_prefix(self):
        # Lightroom Classic keeps Adobe Clean at the top of its install folder.
        lrc = os.path.join(self.adobe, "Adobe Lightroom Classic")
        make_font(os.path.join(lrc, "AdobeClean-Regular.ttf"), "Adobe Clean")
        make_font(os.path.join(lrc, "AdobeClean-Bold.ttf"), "Adobe Clean")
        make_font(os.path.join(lrc, "AdobePiStd.otf"), "Adobe Pi Std")               # not the family
        make_font(os.path.join(lrc, "AdobeCleanUX-Regular.ttf"), "Adobe Clean UX")   # not the family
        self.assertEqual(N._adobe_clean_in_fonts_dir(self.prefix), [])
        res = N.seed_adobe_clean(self.prefix)
        self.assertTrue(res["ok"] and res["present"])
        self.assertEqual(sorted(res["copied"]), ["AdobeClean-Bold.ttf", "AdobeClean-Regular.ttf"])
        self.assertEqual(res["sources"], [os.path.join("Program Files", "Adobe", "Adobe Lightroom Classic")])
        self.assertEqual(sorted(os.listdir(self.fonts)), ["AdobeClean-Bold.ttf", "AdobeClean-Regular.ttf"])

    def test_one_folder_app_before_creative_cloud(self):
        # Photoshop's ui-fonts wins over the Creative Cloud components even with fewer faces:
        # one folder, so no face is registered twice in two formats.
        make_font(os.path.join(self.adobe, "Adobe Photoshop 2026", "Resources", "ui-fonts",
                               "AdobeClean-Regular.otf"), "Adobe Clean")
        cc = os.path.join(self.adobe, "Adobe Creative Cloud", "ACC", "resources", "fonts")
        make_font(os.path.join(cc, "AdobeClean-Light.otf"), "Adobe Clean")
        make_font(os.path.join(cc, "AdobeClean-Bold.otf"), "Adobe Clean")
        res = N.seed_adobe_clean(self.prefix)
        self.assertEqual(res["copied"], ["AdobeClean-Regular.otf"])
        self.assertEqual(res["sources"], [os.path.join("Program Files", "Adobe", "Adobe Photoshop 2026",
                                                       "Resources", "ui-fonts")])

    def test_creative_cloud_is_the_fallback(self):
        # Lightroom (the cloud app) ships only Adobe Clean UX; the Creative Cloud copy is used.
        make_font(os.path.join(self.adobe, "Adobe Lightroom CC", "AdobeCleanUX-Regular.ttf"), "Adobe Clean UX")
        make_font(os.path.join(self.adobe, "Adobe Creative Cloud", "ACC", "resources", "fonts",
                               "AdobeClean-Regular.otf"), "Adobe Clean")
        res = N.seed_adobe_clean(self.prefix)
        self.assertEqual(res["copied"], ["AdobeClean-Regular.otf"])

    def test_cep_web_assets_are_out_of_reach(self):
        deep = os.path.join(self.adobe, "Adobe Premiere Pro 2026", "CEP", "extensions",
                            "com.adobe.frameio.v4", "assets", "AdobeClean-Regular.ttf")
        make_font(deep, "Adobe Clean")
        res = N.seed_adobe_clean(self.prefix)
        self.assertEqual((res["present"], res["copied"]), (False, []))

    def test_prefix_that_already_has_it_is_left_alone(self):
        make_font(os.path.join(self.fonts, "AdobeClean-Regular.ttf"), "Adobe Clean")
        make_font(os.path.join(self.adobe, "Adobe Lightroom Classic", "AdobeClean-Bold.ttf"), "Adobe Clean")
        before = sorted(os.listdir(self.fonts))
        res = N.seed_adobe_clean(self.prefix)
        self.assertEqual((res["ok"], res["present"], res["copied"]), (True, True, []))
        self.assertEqual(sorted(os.listdir(self.fonts)), before)

    def test_no_adobe_app_yet(self):
        res = N.seed_adobe_clean(self.prefix)
        self.assertEqual((res["ok"], res["present"], res["copied"]), (True, False, []))

    def test_never_overwrites(self):
        # A file of the same name that is NOT Adobe Clean stays as it is.
        make_font(os.path.join(self.fonts, "AdobeClean-Regular.ttf"), "Something Else")
        make_font(os.path.join(self.adobe, "Adobe Lightroom Classic", "AdobeClean-Regular.ttf"), "Adobe Clean")
        res = N.seed_adobe_clean(self.prefix)
        self.assertEqual(res["copied"], [])
        self.assertNotIn("Adobe Clean", N.font_family_names(os.path.join(self.fonts, "AdobeClean-Regular.ttf")))

    def test_provision_and_repair_seed_before_registering(self):
        src = open(_CLI).read()
        for start in ("def cmd_prefix_provision(args):", "def repair_prefix_fonts(wine, prefix):"):
            body = src[src.index(start):]
            body = body[:body.index("\ndef ", 1)]
            self.assertIn("seed_adobe_clean(prefix)", body, start)
            self.assertLess(body.index("seed_adobe_clean(prefix)"),
                            body.index("register_prefix_fonts(wine, prefix)"), start)


if __name__ == "__main__":
    unittest.main()
