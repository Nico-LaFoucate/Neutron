#!/usr/bin/env python3
"""Tests for the Bridge and InCopy app profiles (bin/neutron: APP_PROFILES, APP_CATEGORIES,
APP_MIME_TYPES, the shared-mime-info XML and the `launch` app choices).

Mud Hut installs Adobe Bridge 2026 (KBRG) and Adobe InCopy 2026 (AICY) from Adobe's feed; the CLI
has to know where their executables live, which menu categories they go in, and which file types
they own: InCopy owns .icml/.icma, Bridge owns nothing (it is a file browser, every type it shows
belongs to another app). Checked against a KNOWN-BAD too: a CLI without the profiles must fail
these tests (wiki INCIDENTS.md 2026-08-11 / 2026-08-25).

Hermetic: imports bin/neutron as a module; never runs wine.

Run:  python3 tests/test_bridge_incopy.py
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


class Profiles(unittest.TestCase):
    def test_bridge_profile(self):
        p = N.APP_PROFILES["bridge"]
        self.assertEqual(p["name"], "Bridge")
        self.assertTrue(str(p["exe"]).replace("/", "\\").endswith("Adobe Bridge 2026\\Adobe Bridge.exe"), p["exe"])
        self.assertIn("dwrite=b", p["overrides"])
        self.assertRegex(p["accent"], r"^#[0-9a-f]{6}$")

    def test_incopy_profile(self):
        p = N.APP_PROFILES["incopy"]
        self.assertEqual(p["name"], "InCopy")
        self.assertTrue(str(p["exe"]).replace("/", "\\").endswith("Adobe InCopy 2026\\InCopy.exe"), p["exe"])
        self.assertIn("dwrite=b", p["overrides"])
        self.assertRegex(p["accent"], r"^#[0-9a-f]{6}$")

    def test_profiles_match_indesign_base(self):
        # Both start from InDesign's plain profile: same dxvk conf, no app-specific env.
        base = N.APP_PROFILES["indesign"]
        for app in ("bridge", "incopy"):
            self.assertEqual(N.APP_PROFILES[app]["dxvk_conf"], base["dxvk_conf"], app)
            self.assertEqual(N.APP_PROFILES[app]["env"], {}, app)


class MenuAndTypes(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(N.APP_CATEGORIES["bridge"], "Graphics;Photography;Viewer;")
        self.assertEqual(N.APP_CATEGORIES["incopy"], "Office;WordProcessor;Publishing;")

    def test_bridge_claims_no_types(self):
        self.assertNotIn("bridge", N.APP_MIME_TYPES)

    def test_incopy_owns_its_documents(self):
        self.assertEqual(N.APP_MIME_TYPES["incopy"],
                         ("application/x-neutron-icml", "application/x-neutron-icma"))

    def test_mime_xml_has_the_globs(self):
        src = open(_CLI, encoding="utf-8").read()
        for mime, glob in (("application/x-neutron-icml", "*.icml"), ("application/x-neutron-icma", "*.icma")):
            block = src.split('<mime-type type="%s">' % mime, 1)
            self.assertEqual(len(block), 2, mime)
            self.assertIn('<glob pattern="%s"' % glob, block[1].split("</mime-type>", 1)[0])

    def test_every_owned_type_has_xml(self):
        # A type an app owns but the XML never declares would register a dead association.
        src = open(_CLI, encoding="utf-8").read()
        for app in ("incopy",):
            for mime in N.APP_MIME_TYPES[app]:
                self.assertIn('<mime-type type="%s">' % mime, src, mime)


class Launch(unittest.TestCase):
    def test_launch_accepts_both(self):
        for app in ("bridge", "incopy"):
            self.assertIn(app, N.APP_PROFILES)
        src = open(_CLI, encoding="utf-8").read()
        self.assertIn('"incopy_menu_win10"', src)
        self.assertIn(r'HKCU\Software\Wine\AppDefaults\InCopy.exe', src)


if __name__ == "__main__":
    unittest.main()
