#!/usr/bin/env python3
"""Windows programs start in their own folder (2026-10-26).

On Windows an Adobe app starts in its program folder (Adobe's Start-menu shortcuts set "Start in" to the exe's folder) and
a double-clicked installer in the folder it sits in. Neutron used to start every program in whatever Linux folder it was
started from (from the app menu, $HOME = Z:\\home\\<user>): drive-less paths built from HOMEPATH then landed on Z: (Adobe's
plugin installer agent failed that way) and vkd3d-proton wrote its shader cache into that folder.

Run:  python3 tests/test_working_directory.py
"""
import importlib.machinery
import importlib.util
import inspect
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")
_spec = importlib.util.spec_from_loader("neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N)


class WorkingDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutron-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app_dir = os.path.join(self.tmp, "drive_c", "Program Files", "Adobe", "Adobe Photoshop 2026")
        os.makedirs(self.app_dir)
        self.exe = os.path.join(self.app_dir, "Photoshop.exe")
        open(self.exe, "w").close()

    def test_program_dir_is_the_exe_folder(self):
        self.assertEqual(N._program_dir(self.exe), self.app_dir)

    def test_every_windows_program_start_names_its_folder(self):
        for fn in (N.cmd_launch, N._start_adobe_daemons, N._run_installer, N._run_ms_installer):
            src = inspect.getsource(fn)
            self.assertIn("cwd=_program_dir(", src, fn.__name__)

    def test_a_vendor_installer_starts_in_its_own_folder(self):
        downloads = os.path.join(self.tmp, "Downloads")
        os.makedirs(downloads)
        setup = os.path.join(downloads, "setup.exe")
        open(setup, "w").close()
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw)
            return SimpleNamespace(returncode=0)
        with mock.patch.object(N, "NEUTRON_LOGS_DIR", os.path.join(self.tmp, "logs")), \
             mock.patch.object(N.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(N, "wineserver_wait", return_value=None):
            r = N._run_installer(SimpleNamespace(json=True), os.path.join(self.tmp, "prefix"), setup, "/x/wine")
        self.assertTrue(r["ok"])
        self.assertEqual(seen["cwd"], downloads)

    def test_project_paths(self):
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.tmp)
        open(os.path.join(self.tmp, "proj.prproj"), "w").close()
        self.assertEqual(N._project_arg("proj.prproj"), "Z:" + os.path.join(self.tmp, "proj.prproj").replace("/", "\\"))
        self.assertEqual(N._project_arg("/home/u/a b.psd"), "Z:\\home\\u\\a b.psd")
        self.assertEqual(N._project_arg("C:\\Users\\u\\x.aep"), "C:\\Users\\u\\x.aep")   # Collider passes Windows paths
        self.assertEqual(N._project_arg(None), None)


if __name__ == "__main__":
    unittest.main()
