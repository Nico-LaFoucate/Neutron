#!/usr/bin/env python3
"""Tests for neutron-appenv.conf (2026-10-13): an app started BY ANOTHER APP gets its own settings.

Premiere's Dynamic Link started After Effects with Premiere's environment (no splash, black Composition panel).
`neutron launch` now writes <prefix>/neutron-appenv.conf, and Neutron's Wine applies the started app's section
(ntdll `neutron_apply_app_env`; Wine side tested by preserved-fixes/harnesses/appenv-spawn-test.sh).

The invariant tested here: starting from ANY app's launch environment, applying another app's section the way
the Wine hook does (KEY=VALUE sets, -KEY clears) gives exactly that other app's own launch environment.
Nothing here starts wine; the prefix is a temp dir with empty files where the exes would be.

Run:  python3 tests/test_appenv.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load_cli()

EXES = [
    "Program Files/Adobe/Adobe Premiere Pro 2025/Adobe Premiere Pro.exe",
    "Program Files/Adobe/Adobe Premiere Pro 2026/Adobe Premiere Pro.exe",
    "Program Files/Adobe/Adobe After Effects 2025/Support Files/AfterFX.exe",
    "Program Files/Adobe/Adobe After Effects 2026/Support Files/AfterFX.exe",
    "Program Files/Adobe/Adobe Photoshop 2026/Photoshop.exe",
    "Program Files/Adobe/Adobe Lightroom Classic/Lightroom.exe",
    "Program Files/Adobe/Adobe Lightroom CC/lightroom.exe",   # same name as LrC's but for case: must not collide
    "Program Files/Adobe/Adobe Media Encoder 2026/Adobe Media Encoder.exe",
]


def read(path):
    with open(path) as f:
        return f.read()


def parse_conf(path):
    """Read neutron-appenv.conf the way the C hook does: {image path (lowercased): [(key, value or None)]}."""
    sections, cur = {}, None
    for line in read(path).split("\n"):
        if line.startswith("[") and line.endswith("]"):
            cur = sections.setdefault(line[1:-1].lower(), [])
        elif cur is not None and line and not line.startswith("#"):
            cur.append((line[1:], None) if line.startswith("-") else tuple(line.split("=", 1)))
    return sections


def apply_section(env, section):
    env = dict(env)
    for k, v in section:
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


class AppEnvConf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = os.path.join(self.tmp.name, "AE2026")
        for rel in EXES:
            p = os.path.join(self.prefix, "drive_c", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        with open(os.path.join(self.prefix, "neutron-env.conf"), "w") as f:
            f.write("# per-prefix gate\nNEUTRON_TEST_PREFIXWIDE=7\nWINEDLLOVERRIDES=foo=d\n")

    def tearDown(self):
        self.tmp.cleanup()

    def own_env(self, app, exe_rel):
        """What `neutron launch <app>` computes for this exe from a clean shell."""
        profile = cli.APP_PROFILES[app]
        exe = os.path.join(self.prefix, "drive_c", exe_rel)
        env = {}
        cli._apply_app_env(env, app, profile, self.prefix, cli._dxvk_conf_for_exe(self.prefix, profile, exe))
        return env

    def installed(self):
        """[(app, exe_rel)] for every profile exe present in the fake prefix."""
        out = []
        for app, profile in cli.APP_PROFILES.items():
            for exe in cli._app_exe_variants(self.prefix, profile["exe"]):
                out.append((app, os.path.relpath(exe, os.path.join(self.prefix, "drive_c"))))
        return out

    def test_every_installed_exe_has_a_section(self):
        cli.write_appenv_conf(self.prefix)
        sections = parse_conf(os.path.join(self.prefix, cli.APPENV_CONF))
        for rel in EXES:
            self.assertIn(("C:\\" + rel.replace("/", "\\")).lower(), sections, rel)
        self.assertEqual(len(sections), len(EXES))   # LrC and Lightroom CC did not collide

    def test_section_turns_any_parent_env_into_the_childs_own(self):
        cli.write_appenv_conf(self.prefix)
        sections = parse_conf(os.path.join(self.prefix, cli.APPENV_CONF))
        apps = self.installed()
        self.assertGreaterEqual(len(apps), len(EXES))
        for parent_app, parent_exe in apps:
            parent_env = dict(self.own_env(parent_app, parent_exe), PATH="/usr/bin", WINEDEBUG="+seh")
            for child_app, child_exe in apps:
                got = apply_section(parent_env, sections[("C:\\" + child_exe.replace("/", "\\")).lower()])
                want = dict(self.own_env(child_app, child_exe), PATH="/usr/bin", WINEDEBUG="+seh")
                self.assertEqual(got, want, "%s started by %s" % (child_app, parent_app))

    def test_after_effects_from_premiere_regression(self):
        """The 2026-10-13 failure, by name: what After Effects lacked or wrongly carried when Premiere started it."""
        cli.write_appenv_conf(self.prefix)
        sections = parse_conf(os.path.join(self.prefix, cli.APPENV_CONF))
        pr = self.own_env("premiere", EXES[1])
        ae = apply_section(pr, sections[("C:\\" + EXES[3].replace("/", "\\")).lower()])
        self.assertNotIn("NEUTRON_D2D_COMPOSEREAD", ae)          # paints AE's canvas white
        self.assertEqual(ae.get("NEUTRON_DXVK_EXPORT_TEXTURES"), "1")   # composition black without it
        self.assertEqual(ae.get("NEUTRON_WL_ORPHAN_TOPLEVEL"), "1")     # splash never shown without it
        self.assertEqual(ae.get("NEUTRON_DISABLE_BTW"), "1")
        self.assertEqual(ae.get("DXVK_ENABLE_NVAPI"), "1")
        self.assertIn("nvapi64=n", ae.get("WINEDLLOVERRIDES", ""))
        self.assertTrue(ae["DXVK_CONFIG_FILE"].endswith("neutron-ae-dxvk.conf"))
        self.assertEqual(ae["NEUTRON_APP"], "aftereffects")
        self.assertTrue(ae["NEUTRON_WAYLAND_APP_ID"].startswith("neutron-aftereffects-"))

    def test_prefix_conf_reaches_started_apps_but_caller_env_does_not(self):
        os.environ["NEUTRON_TEST_CALLER_ONLY"] = "1"
        try:
            cli.write_appenv_conf(self.prefix)
        finally:
            del os.environ["NEUTRON_TEST_CALLER_ONLY"]
        text = read(os.path.join(self.prefix, cli.APPENV_CONF))
        self.assertNotIn("NEUTRON_TEST_CALLER_ONLY", text)
        for section in parse_conf(os.path.join(self.prefix, cli.APPENV_CONF)).values():
            self.assertIn(("NEUTRON_TEST_PREFIXWIDE", "7"), section)
            self.assertTrue(dict(s for s in section if s[1] is not None)["WINEDLLOVERRIDES"].startswith("foo=d;"))

    def test_launch_env_keeps_caller_overrides(self):
        """A direct launch: a variable set by the caller still beats the profile (Wine leaves this app alone)."""
        env = {"NEUTRON_D2D_COMPOSEREAD": "0"}
        profile = cli.APP_PROFILES["premiere"]
        cli._apply_app_env(env, "premiere", profile, self.prefix, "", protected={"NEUTRON_D2D_COMPOSEREAD"})
        self.assertEqual(env["NEUTRON_D2D_COMPOSEREAD"], "0")
        self.assertEqual(env["NEUTRON_APP"], "premiere")


if __name__ == "__main__":
    unittest.main()
