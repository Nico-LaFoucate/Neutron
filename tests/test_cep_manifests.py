#!/usr/bin/env python3
"""Tests for the CEP manifest restore and signature check in bin/neutron (2026-10-12).

Through 1.0.0-beta.5, `prefix provision` added three CEF flags to aescripts' CEP manifests. The
manifest is listed in the extension's META-INF/signatures.xml, so CEP refused every edited
extension ("Signature verification failed") unless PlayerDebugMode was on. Provision now puts
back the signed original, picking the candidate whose SHA-256 matches the signature, and leaves
alone anything it cannot match.

The extension here is synthetic: a manifest laid out like Captioneer's (two <CEFCommandLine>
blocks, closing tag indented 8 spaces), one script, and a signatures.xml with their digests.
`_old_patch` is the exact insertion the old patcher made. The signature check's verdicts were
validated against CEP12's own on 2026-10-12 (see cep_signature_status).

Run:  python3 tests/test_cep_manifests.py
"""
import base64
import hashlib
import importlib.machinery
import importlib.util
import os
import re
import shutil
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

EXT_ID = "com.example.panel"
MANIFEST = b"""<?xml version="1.0" encoding="UTF-8"?>
<ExtensionManifest Version="7.0" ExtensionBundleId="com.example.panel">
  <DispatchInfoList>
    <Extension Id="com.example.panel.main">
      <DispatchInfo>
        <Resources>
        <CEFCommandLine>
            <Parameter>--enable-nodejs</Parameter>
            <Parameter>--mixed-context</Parameter>
        </CEFCommandLine>
        </Resources>
      </DispatchInfo>
    </Extension>
    <Extension Id="com.example.panel.helper">
      <DispatchInfo>
        <Resources>
        <CEFCommandLine>
            <Parameter>--no-sandbox</Parameter>
        </CEFCommandLine>
        </Resources>
      </DispatchInfo>
    </Extension>
  </DispatchInfoList>
</ExtensionManifest>
"""
SCRIPT = b"console.log('panel');\n"


def _old_patch(data):
    """What ensure_cep_flags (1.0.0-beta.5) wrote: the missing flags appended to each block."""
    flags = ("--no-sandbox", "--disable-gpu-sandbox", "--disable-direct-composition")

    def _add(m):
        block = m.group(0)
        have = set(re.findall(r"<Parameter>([^<]*)</Parameter>", block))
        ins = "".join("\n            <Parameter>%s</Parameter>" % f for f in flags if f not in have)
        return block.replace("</CEFCommandLine>", ins + "\n         </CEFCommandLine>") if ins else block
    return re.sub(r"<CEFCommandLine>.*?</CEFCommandLine>", _add, data.decode(), flags=re.S).encode()


def _digest(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


class _Ext:
    """A prefix holding one signed CEP extension."""

    def __init__(self, root):
        self.prefix = os.path.join(root, "prefix")
        self.dir = os.path.join(self.prefix, "drive_c", "Program Files (x86)", "Common Files",
                                "Adobe", "CEP", "extensions", EXT_ID)
        for sub in ("CSXS", "META-INF", "js"):
            os.makedirs(os.path.join(self.dir, sub))
        self.man = os.path.join(self.dir, "CSXS", "manifest.xml")
        self.bak = self.man + N.CEP_MANIFEST_BACKUP_SUFFIX
        self.write("CSXS/manifest.xml", MANIFEST)
        self.write("js/main.js", SCRIPT)
        refs = "".join(
            '<Reference URI="%s"><DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
            '<DigestValue>%s</DigestValue></Reference>\n' % (rel, _digest(data))
            for rel, data in (("CSXS/manifest.xml", MANIFEST), ("js/main.js", SCRIPT)))
        self.write("META-INF/signatures.xml",
                   ('<Signature><SignedInfo><Reference URI="#PackageSignature">'
                    '<DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
                    '<DigestValue>x</DigestValue></Reference></SignedInfo><Object><Manifest>\n'
                    + refs + "</Manifest></Object></Signature>\n").encode())

    def write(self, rel, data):
        with open(os.path.join(self.dir, rel), "wb") as f:
            f.write(data)

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ext = _Ext(self._tmp.name)

    def _edit_like_beta5(self, extra=b""):
        e = self.ext
        with open(e.bak, "wb") as f:
            f.write(MANIFEST)
        e.write("CSXS/manifest.xml", _old_patch(MANIFEST) + extra)

    def test_old_edit_is_stripped_back_to_the_signed_bytes(self):
        self._edit_like_beta5()
        self.assertEqual(N.cep_signature_status(self.ext.dir), ([], ["CSXS/manifest.xml"]))
        self.assertEqual(N.restore_cep_manifests(self.ext.prefix), ([EXT_ID], []))
        self.assertEqual(self.ext.read(self.ext.man), MANIFEST)
        self.assertFalse(os.path.exists(self.ext.bak))
        self.assertEqual(N.cep_signature_status(self.ext.dir), ([], []))

    def test_stale_backup_does_not_block_the_strip(self):
        # The extension updated after the backup was taken, and the old patcher re-edited it.
        self._edit_like_beta5()
        with open(self.ext.bak, "wb") as f:
            f.write(b"<an older version's manifest/>\n")
        self.assertEqual(N.restore_cep_manifests(self.ext.prefix), ([EXT_ID], []))
        self.assertEqual(self.ext.read(self.ext.man), MANIFEST)

    def test_backup_is_used_when_the_file_was_edited_further(self):
        self._edit_like_beta5(extra=b"<!-- hand edit -->\n")
        self.assertEqual(N.restore_cep_manifests(self.ext.prefix), ([EXT_ID], []))
        self.assertEqual(self.ext.read(self.ext.man), MANIFEST)

    def test_nothing_matches_so_nothing_is_written(self):
        hand = MANIFEST.replace(b"--mixed-context", b"--mixed-context --v=1")
        self.ext.write("CSXS/manifest.xml", hand)
        with open(self.ext.bak, "wb") as f:
            f.write(b"<an older version's manifest/>\n")
        self.assertEqual(N.restore_cep_manifests(self.ext.prefix), ([], [EXT_ID]))
        self.assertEqual(self.ext.read(self.ext.man), hand)
        self.assertTrue(os.path.exists(self.ext.bak))

    def test_original_manifest_only_loses_the_leftover_backup(self):
        with open(self.ext.bak, "wb") as f:
            f.write(MANIFEST)
        self.assertEqual(N.restore_cep_manifests(self.ext.prefix), ([], []))
        self.assertEqual(self.ext.read(self.ext.man), MANIFEST)
        self.assertFalse(os.path.exists(self.ext.bak))

    def test_extension_neutron_never_edited_is_not_touched(self):
        hand = MANIFEST + b"<!-- the user's own edit -->\n"
        self.ext.write("CSXS/manifest.xml", hand)
        self.assertEqual(N.restore_cep_manifests(self.ext.prefix), ([], []))
        self.assertEqual(self.ext.read(self.ext.man), hand)


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ext = _Ext(self._tmp.name)

    def test_intact(self):
        self.assertEqual(N.cep_signature_status(self.ext.dir), ([], []))

    def test_missing_and_changed_files(self):
        os.remove(os.path.join(self.ext.dir, "js", "main.js"))
        self.ext.write("CSXS/manifest.xml", MANIFEST + b"\n")
        self.assertEqual(N.cep_signature_status(self.ext.dir),
                         (["js/main.js"], ["CSXS/manifest.xml"]))

    def test_unsigned_extension(self):
        os.remove(os.path.join(self.ext.dir, "META-INF", "signatures.xml"))
        self.assertIsNone(N.cep_signature_status(self.ext.dir))

    def test_damage_is_split_between_ours_and_the_vendors(self):
        vendor = self.ext                                   # com.example.panel
        os.remove(os.path.join(vendor.dir, "js", "main.js"))
        adobe = os.path.join(os.path.dirname(vendor.dir), "com.adobe.ccx.start-2.16.0")
        edited = os.path.join(os.path.dirname(vendor.dir), "com.aescripts.captioneer")
        for d in (adobe, edited):
            shutil.copytree(vendor.dir, d)
        with open(os.path.join(adobe, "CSXS", "manifest.xml"), "ab") as f:
            f.write(b"\n")
        with open(os.path.join(edited, "CSXS", "manifest.xml" + N.CEP_MANIFEST_BACKUP_SUFFIX), "wb") as f:
            f.write(MANIFEST)
        ours, theirs = N.cep_extension_damage(vendor.prefix)
        self.assertEqual([e["id"] for e in ours], ["com.adobe.ccx.start-2.16.0", "com.aescripts.captioneer"])
        self.assertEqual([(e["id"], e["missing"], e["changed"]) for e in theirs],
                         [("com.example.panel", 1, 0)])
        self.assertEqual(ours[1]["edited_by_neutron"], True)
        self.assertEqual(ours[0]["changed"], 1)

    def test_extension_name(self):
        self.assertEqual(N.cep_extension_name(self.ext.man), "com.example.panel")
        self.ext.write("CSXS/manifest.xml", MANIFEST.replace(
            b"<DispatchInfo>", b"<DispatchInfo><UI><Menu>%LOCALIZED</Menu><Menu> Light Equalizer </Menu></UI>", 1))
        self.assertEqual(N.cep_extension_name(self.ext.man), "Light Equalizer")
        self.ext.write("CSXS/manifest.xml", MANIFEST.replace(
            b'ExtensionBundleId="com.example.panel"',
            b'ExtensionBundleId="com.example.panel" ExtensionBundleName="Captioneer"'))
        self.assertEqual(N.cep_extension_name(self.ext.man), "Captioneer")

    def test_debug_mode_versions(self):
        with open(os.path.join(self.ext.prefix, "user.reg"), "w") as f:
            f.write('[Software\\\\Adobe\\\\CSXS.11] 1\n"Other"="1"\n\n'
                    '[Software\\\\Adobe\\\\CSXS.12] 1\n#time=1\n"PlayerDebugMode"="1"\n\n'
                    '[Software\\\\Adobe\\\\CSXS.9] 1\n"PlayerDebugMode"="1"\n')
        self.assertEqual(N._cep_debug_mode(self.ext.prefix), ["9", "12"])

    def test_runtime_gate(self):
        self.assertTrue(N._runtime_at_least("11.10-108", "11.10-108"))
        self.assertTrue(N._runtime_at_least("11.10-110", "11.10-108"))
        self.assertTrue(N._runtime_at_least("11.11-1", "11.10-108"))
        self.assertFalse(N._runtime_at_least("11.10-97", "11.10-108"))
        self.assertFalse(N._runtime_at_least(None, "11.10-108"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
