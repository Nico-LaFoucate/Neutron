#!/usr/bin/env python3
"""`neutron plugins install|list|folder` (2026-10-26).

Plugins go where their Windows installers put them: .aex/.prm into the MediaCore folder After Effects, Premiere Pro and
Media Encoder share, Photoshop and Illustrator plugins into the app's Plug-ins folder, scripts into the app's scripts
folder, a .zxp unpacked into the CEP extensions folder under its bundle id with its signature checked BEFORE anything is
replaced. Vendor installers run in the prefix; that path needs Wine and is covered by the lab, not here.

Run:  python3 tests/test_plugins.py
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli(env):
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_loader(
            "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


MANIFEST = ('<?xml version="1.0"?><ExtensionManifest Version="7.0" ExtensionBundleId="com.example.panel" '
            'ExtensionBundleVersion="1.2.0" ExtensionBundleName="Example Panel"></ExtensionManifest>')


class Plugins(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="neutron-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = {"HOME": self.home, "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                    "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_CACHE_HOME": os.path.join(self.home, ".cache")}
        self.cli = _load_cli(self.env)
        self.prefix = os.path.join(self.home, "Adobe")
        os.makedirs(os.path.join(self.prefix, "drive_c", "users", "u"))
        self.files = os.path.join(self.home, "files")
        os.makedirs(self.files)

    def app(self, app_id, year="2026"):
        exe = os.path.join(self.prefix, self.cli.APP_PROFILES[app_id]["exe"].replace("2025", year).replace("2024", year))
        os.makedirs(os.path.dirname(exe), exist_ok=True)
        open(exe, "w").close()

    def file(self, name, data="x"):
        p = os.path.join(self.files, name)
        with open(p, "w") as f:
            f.write(data)
        return p

    def zxp(self, name, drop_signed_file=False, unsigned=False):
        """A .zxp whose META-INF/signatures.xml carries the real digests of its files, as CEP checks them."""
        tree = os.path.join(self.files, name + ".tree")
        os.makedirs(os.path.join(tree, "CSXS"))
        with open(os.path.join(tree, "CSXS", "manifest.xml"), "w") as f:
            f.write(MANIFEST)
        with open(os.path.join(tree, "index.js"), "w") as f:
            f.write("console.log(1)")
        if not unsigned:
            self.sign(tree)
        if drop_signed_file:
            os.remove(os.path.join(tree, "index.js"))
        path = os.path.join(self.files, name)
        with zipfile.ZipFile(path, "w") as z:
            for root, _d, fs in os.walk(tree):
                for f in fs:
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, tree))
        return path

    def sign(self, tree):
        """Write a META-INF/signatures.xml the way cep_signature_status reads one."""
        import base64, hashlib
        refs = []
        for rel in ("CSXS/manifest.xml", "index.js"):
            with open(os.path.join(tree, rel), "rb") as f:
                digest = base64.b64encode(hashlib.sha256(f.read()).digest()).decode()
            refs.append('<Reference URI="%s"><DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
                        '<DigestValue>%s</DigestValue></Reference>' % (rel, digest))
        os.makedirs(os.path.join(tree, "META-INF"))
        with open(os.path.join(tree, "META-INF", "signatures.xml"), "w") as f:
            f.write('<?xml version="1.0"?><signatures><Signature Id="PackageSignature"><SignedInfo>%s</SignedInfo>'
                    '</Signature></signatures>' % "".join(refs))

    def install(self, *argv):
        args = self.cli.build_parser().parse_args(["--json", "plugins", "install", "--prefix", self.prefix, *argv])
        buf = io.StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(buf):
            try:
                rc = args.func(args)
            except SystemExit as e:
                rc = e.code
        return rc, json.loads(buf.getvalue())

    def drive(self, *parts):
        return os.path.join(self.prefix, "drive_c", *parts)

    def test_signature_reader_accepts_the_test_package(self):
        tree = os.path.join(self.files, "t")
        os.makedirs(os.path.join(tree, "CSXS"))
        with open(os.path.join(tree, "CSXS", "manifest.xml"), "w") as f:
            f.write(MANIFEST)
        with open(os.path.join(tree, "index.js"), "w") as f:
            f.write("console.log(1)")
        self.sign(tree)
        self.assertEqual(self.cli.cep_signature_status(tree), ([], []))

    def test_shared_plugins_go_to_mediacore(self):
        aex = self.file("Effect.aex")
        folder = os.path.join(self.files, "VendorFX")
        os.makedirs(os.path.join(folder, "sub"))
        open(os.path.join(folder, "sub", "Fx.aex"), "w").close()
        rc, out = self.install(aex, folder)
        self.assertEqual(rc, 0, out)
        mc = self.drive("Program Files", "Adobe", "Common", "Plug-ins", "7.0", "MediaCore")
        self.assertTrue(os.path.isfile(os.path.join(mc, "Effect.aex")))
        self.assertTrue(os.path.isfile(os.path.join(mc, "VendorFX", "sub", "Fx.aex")))

    def test_vst3_file_and_bundle_go_to_common_vst3(self):
        single = self.file("Single.vst3")
        bundle = os.path.join(self.files, "Pro-Q.vst3")
        os.makedirs(os.path.join(bundle, "Contents", "x86_64-win"))
        open(os.path.join(bundle, "Contents", "x86_64-win", "Pro-Q.vst3"), "w").close()
        rc, out = self.install(single, bundle)
        self.assertEqual(rc, 0, out)
        vst3 = self.drive("Program Files", "Common Files", "VST3")
        self.assertTrue(os.path.isfile(os.path.join(vst3, "Single.vst3")))
        self.assertTrue(os.path.isfile(os.path.join(vst3, "Pro-Q.vst3", "Contents", "x86_64-win", "Pro-Q.vst3")))
        self.assertEqual(self.cli.plugins_inventory(self.prefix)["vst3"], ["Pro-Q.vst3", "Single.vst3"])
        self.assertIn("Scan for Plug-Ins", out["installed"][0]["note"])

    def test_an_installer_that_adds_vst3_says_how_to_load_it(self):
        exe = self.file("setup.exe")
        vst3 = self.drive("Program Files", "Common Files", "VST3")

        def fake_installer(args, prefix, path, wine):
            os.makedirs(vst3, exist_ok=True)
            open(os.path.join(vst3, "Vendor EQ.vst3"), "w").close()
            return {"ok": True}
        with mock.patch.object(self.cli, "_running_app_ids", return_value=[]), \
             mock.patch.object(self.cli, "resolve_wine", return_value=("/x/wine", True)), \
             mock.patch.object(self.cli, "stamp_mismatch", return_value=False), \
             mock.patch.object(self.cli, "_run_installer", side_effect=fake_installer):
            rc, out = self.install(exe)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["installed"][0]["vst3"], ["Vendor EQ.vst3"])
        self.assertIn("Manage Audio Plug-ins", out["installed"][0]["note"])

    def test_replacing_keeps_the_old_file_for_a_running_app(self):
        aex = self.file("Effect.aex", "new")
        mc = self.drive("Program Files", "Adobe", "Common", "Plug-ins", "7.0", "MediaCore")
        os.makedirs(mc)
        with open(os.path.join(mc, "Effect.aex"), "w") as f:
            f.write("old")
        held = open(os.path.join(mc, "Effect.aex"))         # an app with the plugin loaded
        self.addCleanup(held.close)
        rc, out = self.install(aex)
        self.assertEqual(rc, 0)
        self.assertTrue(out["installed"][0]["replaced"])
        self.assertEqual(held.read(), "old")                  # replaced by rename, not rewritten in place
        with open(os.path.join(mc, "Effect.aex")) as f:
            self.assertEqual(f.read(), "new")

    def test_photoshop_plugin_needs_photoshop(self):
        f8 = self.file("Filter.8bf")
        rc, out = self.install(f8)
        self.assertNotEqual(rc, 0)
        self.assertIn("Photoshop is not installed", out["installed"][0]["reason"])
        self.app("photoshop")
        rc, out = self.install(f8)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out["installed"][0]["to"].endswith(os.path.join("Adobe Photoshop 2026", "Plug-ins", "Filter.8bf")))

    def test_scripts_need_the_app(self):
        js = self.file("Panel.jsx")
        self.app("aftereffects")
        rc, out = self.install(js)
        self.assertNotEqual(rc, 0)
        self.assertIn("--app", out["installed"][0]["reason"])
        rc, out = self.install("--app", "aftereffects", js)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out["installed"][0]["to"].endswith(os.path.join("Scripts", "ScriptUI Panels", "Panel.jsx")))

    def test_zxp_unpacks_under_its_bundle_id(self):
        rc, out = self.install(self.zxp("good.zxp"))
        self.assertEqual(rc, 0, out)
        r = out["installed"][0]
        self.assertEqual((r["id"], r["version"], r["signature"]), ("com.example.panel", "1.2.0", "valid"))
        self.assertTrue(os.path.isfile(self.drive("Program Files (x86)", "Common Files", "Adobe", "CEP", "extensions",
                                                  "com.example.panel", "CSXS", "manifest.xml")))

    def test_a_damaged_zxp_changes_nothing(self):
        self.assertEqual(self.install(self.zxp("good.zxp"))[0], 0)
        rc, out = self.install(self.zxp("bad.zxp", drop_signed_file=True))
        self.assertNotEqual(rc, 0)
        self.assertIn("nothing was changed", out["installed"][0]["reason"])
        ext = self.drive("Program Files (x86)", "Common Files", "Adobe", "CEP", "extensions")
        self.assertEqual(self.cli.cep_signature_status(os.path.join(ext, "com.example.panel")), ([], []))
        self.assertEqual([n for n in os.listdir(ext) if n.startswith(".")], [])

    def test_unsigned_zxp_installs_with_a_note(self):
        rc, out = self.install(self.zxp("unsigned.zxp", unsigned=True))
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["installed"][0]["signature"], "unsigned")
        self.assertIn("PlayerDebugMode", out["installed"][0]["note"])

    def test_ccx_and_unknown_types_are_refused(self):
        rc, out = self.install(self.file("p.ccx"), self.file("readme.txt"))
        self.assertNotEqual(rc, 0)
        self.assertIn("UXP", out["installed"][0]["reason"])
        self.assertIn("not a plugin type", out["installed"][1]["reason"])
        self.assertNotIn(".ccx", out["installed"][1]["reason"])

    def test_installers_wait_for_closed_apps(self):
        exe = self.file("setup.exe")
        with mock.patch.object(self.cli, "_running_app_ids", return_value=["aftereffects"]):
            rc, out = self.install(exe)
        self.assertNotEqual(rc, 0)
        self.assertIn("close After Effects first", out["installed"][0]["reason"])

    def test_list_reads_extensions_and_vendor_programs(self):
        self.install(self.zxp("good.zxp"))
        with open(os.path.join(self.prefix, "system.reg"), "w") as f:
            f.write('WINE REGISTRY Version 2\n\n'
                    '[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\BorisFX] 1700000000\n'
                    '"DisplayName"="Boris FX Sapphire"\n"Publisher"="Boris FX"\n"DisplayVersion"="2026.0"\n\n'
                    '[Software\\\\Wow6432Node\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\Adobe] 1700000000\n'
                    '"DisplayName"="Adobe Genuine Service"\n"Publisher"="Adobe Inc."\n\n')
        inv = self.cli.plugins_inventory(self.prefix)
        self.assertEqual([e["id"] for e in inv["extensions"]], ["com.example.panel"])
        self.assertEqual(inv["programs"], [{"name": "Boris FX Sapphire", "publisher": "Boris FX", "version": "2026.0"}])


if __name__ == "__main__":
    unittest.main()
