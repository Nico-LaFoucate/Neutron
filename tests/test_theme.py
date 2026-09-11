#!/usr/bin/env python3
"""Tests for the DEFAULT NEUTRON THEME (bin/neutron).

The first automated test of the CLI. It exists because the theme moved here from Collider on
2026-09-11 — the engine owns the default, the GUI only chooses colours — and the Collider tests
that covered the .reg format were deleted in the same change. Deleting a test without replacing it
is how a format quietly rots.

Run:  python3 tests/test_theme.py
"""
import importlib.util
import os
import re
import sys
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    """Import bin/neutron as a module. It has no .py suffix, so spec_from_file_location
    needs the loader spelled out."""
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


class DefaultTheme(unittest.TestCase):
    def test_palette_values_are_wine_rgb_triples(self):
        """Wine's Control Panel\\Colors wants "R G B" decimal, not hex. A malformed value is
        silently ignored, which reads as 'the theme didn't apply'."""
        for key, val in N.DEFAULT_THEME_COLORS.items():
            parts = val.split()
            self.assertEqual(len(parts), 3, f"{key}={val!r} is not three components")
            for p in parts:
                self.assertTrue(p.isdigit(), f"{key}={val!r} is not decimal")
                self.assertLessEqual(int(p), 255, f"{key}={val!r} out of range")

    def test_reg_text_has_both_halves(self):
        """⛔ The palette alone is not a theme. Wine's wine.inf enables its bundled Aero visual
        style in every prefix, and comctl32 v6 controls then paint from THAT and ignore the
        palette entirely — which is why Open/Cancel and column headers rendered light on an
        otherwise dark dialog. Both sections, or the theme stops at the controls."""
        txt = N.theme_reg_text()
        self.assertTrue(txt.startswith("REGEDIT4"))
        self.assertIn(r"[HKEY_CURRENT_USER\Control Panel\Colors]", txt)
        self.assertIn(r"CurrentVersion\ThemeManager", txt)
        self.assertIn('"ThemeActive"="0"', txt)
        self.assertLess(txt.index("Control Panel"), txt.index("ThemeManager"),
                        "colours must come before the visual-style switch")

    def test_crlf_line_endings(self):
        """.reg files are CRLF. regedit tolerates LF for simple cases, but mixed endings have
        bitten before, so assert every LF is preceded by a CR — no bare newlines."""
        txt = N.theme_reg_text()
        self.assertIn("\r\n", txt)
        bare = [m.start() for m in re.finditer(r"(?<!\r)\n", txt)]
        self.assertEqual(bare, [], f"bare LF at offsets {bare[:5]}")

    def test_custom_colors_replace_the_palette_but_never_the_switch(self):
        """Collider hands the user's colours to the engine. Those replace the palette — they must
        not be able to drop the visual-style switch, or a customized theme silently regresses."""
        txt = N.theme_reg_text({"ButtonFace": "10 20 30"})
        self.assertIn('"ButtonFace"="10 20 30"', txt)
        self.assertNotIn('"43 43 43"', txt)
        self.assertIn('"ThemeActive"="0"', txt)

    def test_dark_chrome_is_actually_dark(self):
        """A sanity floor: the default is the dark theme. If someone edits the map, catch a
        light value landing in the chrome rather than discovering it in a screenshot."""
        for key in ("ActiveTitle", "Window", "ButtonFace", "Menu"):
            r, g, b = (int(x) for x in N.DEFAULT_THEME_COLORS[key].split())
            self.assertLess((r + g + b) / 3, 96, f"{key} is not a dark value")
        for key in ("WindowText", "ButtonText", "TitleText"):
            r, g, b = (int(x) for x in N.DEFAULT_THEME_COLORS[key].split())
            self.assertGreater((r + g + b) / 3, 160, f"{key} would be unreadable on dark chrome")


if __name__ == "__main__":
    unittest.main(verbosity=2)
