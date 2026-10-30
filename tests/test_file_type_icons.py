#!/usr/bin/env python3
"""Tests for the project-file icons `prefix provision` installs (bin/neutron: install_file_type_icons).

Windows reads a file's icon from the program named by its ProgID's DefaultIcon. Provision does the same from the prefix's
registry on disk, so a file manager shows Adobe's icon for .psd, .prproj and the rest. The prefix here is synthetic: a
.reg file, and a minimal PE with three icon groups. Nothing starts wine.

Run:  python3 tests/test_file_type_icons.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import struct
import tempfile
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli(data_home, config_home):
    env = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME")}
    os.environ.update(XDG_DATA_HOME=data_home, XDG_CONFIG_HOME=config_home)
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return mod


def png(size, mark):
    """Not a real image: the header carries the size, the last byte says which group it came from."""
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", size, size) + bytes([mark])


def pe(groups):
    """A minimal PE32+ whose resources are `groups`: one list of icon sizes per RT_GROUP_ICON, ids 1, 2, 3..."""
    icons, gdata, next_id = [], [], 1
    for g, sizes in enumerate(groups):
        ent = b""
        for size in sizes:
            icons.append((next_id, png(size, g)))
            ent += struct.pack("<BBBBHHIH", size & 255, size & 255, 0, 0, 1, 32, 0, next_id)
            next_id += 1
        gdata.append((g + 1, struct.pack("<HHH", 0, 1, len(sizes)) + ent))

    def directory(n):
        return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, n)

    def tree(items, base):
        """(id, blob) leaves under one type: id dir -> lang dir -> data entry, offsets from the root at `base`."""
        head = directory(len(items))
        size = len(head) + 8 * len(items)
        ids, langs, datas = b"", b"", []
        lang_off = base + size
        data_off = lang_off + (len(directory(1)) + 8) * len(items)
        for k, (rid, _) in enumerate(items):
            ids += struct.pack("<II", rid, 0x80000000 | (lang_off + k * (len(directory(1)) + 8)))
            langs += directory(1) + struct.pack("<II", 1033, data_off + k * 16)
        return head + ids + langs, data_off + 16 * len(items)

    section_rva, root = 0x1000, directory(2)
    root_size = len(root) + 16
    t_icons, end_icons = tree(icons, root_size)
    t_groups, end_groups = tree(gdata, end_icons)
    blob, offs = b"", []
    base = end_groups
    for _, data in icons + gdata:
        offs.append(base + len(blob))
        blob += data
    # data entries sit right after each tree's lang dirs: fill them in
    def entries(items, start):
        return b"".join(struct.pack("<IIII", section_rva + offs[start + i], len(items[i][1]), 0, 0) for i in range(len(items)))
    t_icons += entries(icons, 0)
    t_groups += entries(gdata, len(icons))
    res = (root + struct.pack("<II", 3, 0x80000000 | root_size) + struct.pack("<II", 14, 0x80000000 | end_icons)
           + t_icons + t_groups + blob)

    file_off = 0x200
    opt = struct.pack("<H", 0x20b) + bytes(110) + bytes(16) + struct.pack("<II", section_rva, len(res)) + bytes(16 * 8 - 8)
    sec = bytes(8) + struct.pack("<IIII", len(res), section_rva, len(res), file_off) + bytes(16)
    head = b"MZ" + bytes(0x3a) + struct.pack("<I", 0x40) + b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, len(opt), 0)
    d = head + opt + sec
    return d + bytes(file_off - len(d)) + res


APP_EXE = r"C:\Program Files\Adobe\App\App.exe"


class FileTypeIcons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutron-fileicons-")
        self.prefix = os.path.join(self.tmp, "Prefix")
        self.data = os.path.join(self.tmp, "data")
        self.cli = _load_cli(self.data, os.path.join(self.tmp, "config"))
        self.exe = os.path.join(self.prefix, "drive_c", "Program Files", "Adobe", "App", "App.exe")
        os.makedirs(os.path.dirname(self.exe))
        self.exe_win = APP_EXE.replace("\\", "\\\\")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def reg(self, *sections):
        """Each section = (key below Classes, default value, optional extra lines)."""
        out = "WINE REGISTRY Version 2\n\n"
        for key, default, *extra in sections:
            out += "[Software\\\\Classes\\\\%s] 1\n" % key.replace("\\", "\\\\")
            if default is not None:
                out += '@="%s"\n' % default.replace("\\", "\\\\").replace('"', '\\"')
            out += "".join(line + "\n" for line in extra) + "\n"
        with open(os.path.join(self.prefix, "system.reg"), "w") as f:
            f.write(out)

    def source(self, ext):
        return self.cli._file_type_icon_source(self.prefix, self.cli._reg_classes(self.prefix), ext, self.exe)

    def test_progid_that_opens_the_file_supplies_the_icon(self):
        self.reg((".psd", "Other.Psd"),
                 (".psd\\OpenWithProgids", None, '"App.Image"=""'),
                 ("Other.Psd\\DefaultIcon", '"C:\\Other\\Other.exe",-1012'),
                 ("App.Image\\DefaultIcon", APP_EXE + ",1"),
                 ("App.Image\\shell\\open\\command", '"%s" "%%1"' % APP_EXE))
        self.assertEqual(self.source("psd"), (self.exe, 1))

    def test_unsigned_index_is_a_resource_id(self):
        self.reg((".indd", "App.Doc"),
                 ("App.Doc\\DefaultIcon", APP_EXE + ",4294967163"),
                 ("App.Doc\\shell\\open\\command", '"%s" "%%1"' % APP_EXE))
        self.assertEqual(self.source("indd"), (self.exe, -133))

    def test_no_progid_of_this_app_means_no_icon(self):
        self.reg((".aep", "Other.Aep"),
                 ("Other.Aep\\DefaultIcon", '"C:\\Other\\Other.exe",1'),
                 ("Other.Aep\\shell\\open\\command", '"C:\\Other\\Other.exe" "%1"'))
        self.assertIsNone(self.source("aep"))

    def test_index_picks_the_group_as_extracticon_does(self):
        with open(self.exe, "wb") as f:
            f.write(pe([[256, 32], [256, 48], [32, 20]]))
        get = self.cli._pe_icon_group_pngs
        self.assertEqual(sorted(get(self.exe, 0)), [32, 256])
        self.assertEqual(sorted(get(self.exe, 1)), [48, 256])
        self.assertEqual(get(self.exe, 1)[256][-1], 1)
        self.assertEqual(get(self.exe, -3)[32][-1], 2)       # negative = resource id
        self.assertEqual(get(self.exe, 9)[32][-1], 2)        # past the end = the last group
        self.assertEqual(get(self.exe, -9), {})

    def test_install_writes_icons_and_only_lists_what_exists(self):
        with open(self.exe, "wb") as f:
            f.write(pe([[256], [256, 32, 20]]))
        self.reg((".prproj", "App.Project"),
                 ("App.Project\\DefaultIcon", APP_EXE + ",1"),
                 ("App.Project\\shell\\open\\command", '"%s" "%%1"' % APP_EXE))
        self.cli._resolve_app_exe = lambda prefix, exe: self.exe
        written = [{"app": "premiere", "mime": ["application/x-neutron-prproj"], "file": "neutron-premiere-prefix.desktop"},
                   {"app": "aftereffects", "mime": ["application/x-neutron-aep"], "file": "neutron-aftereffects-prefix.desktop"}]
        self.assertEqual(self.cli.install_file_type_icons(self.prefix, written), ["prproj"])
        root = os.path.join(self.data, "icons", "hicolor")
        self.assertTrue(os.path.isfile(os.path.join(root, "256x256", "mimetypes", "neutron-file-prproj.png")))
        self.assertTrue(os.path.isfile(os.path.join(root, "32x32", "mimetypes", "neutron-file-prproj.png")))
        self.assertFalse(os.path.exists(os.path.join(root, "20x20")))     # hicolor has no such size
        with open(os.path.join(self.data, "mime", "packages", "neutron-file-icons.xml")) as f:
            xml = f.read()
        self.assertIn('type="application/x-neutron-prproj"><icon name="neutron-file-prproj"/>', xml)
        self.assertNotIn("x-neutron-aep", xml)

    def test_the_default_handlers_prefix_supplies_the_icon(self):
        with open(self.exe, "wb") as f:
            f.write(pe([[256], [256]]))
        self.reg((".prproj", "App.Project"),
                 ("App.Project\\DefaultIcon", APP_EXE + ",1"),
                 ("App.Project\\shell\\open\\command", '"%s" "%%1"' % APP_EXE))
        self.cli._resolve_app_exe = lambda prefix, exe: self.exe
        icon = os.path.join(self.data, "icons", "hicolor", "256x256", "mimetypes", "neutron-file-prproj.png")
        os.makedirs(os.path.dirname(icon))
        with open(icon, "wb") as f:
            f.write(b"from the other prefix")
        os.makedirs(os.path.join(self.tmp, "config"))
        with open(os.path.join(self.tmp, "config", "mimeapps.list"), "w") as f:
            f.write("[Default Applications]\napplication/x-neutron-prproj=neutron-premiere-other.desktop\n")
        written = [{"app": "premiere", "mime": ["application/x-neutron-prproj"], "file": "neutron-premiere-prefix.desktop"}]
        self.cli.install_file_type_icons(self.prefix, written)
        with open(icon, "rb") as f:
            self.assertEqual(f.read(), b"from the other prefix")


if __name__ == "__main__":
    unittest.main()
