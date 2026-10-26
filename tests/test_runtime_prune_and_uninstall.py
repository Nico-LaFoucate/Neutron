#!/usr/bin/env python3
"""`neutron runtime list|prune`, and uninstall removes Mud Hut's cache (2026-10-26).

Runtimes are about 1.1 GB each and nothing removed old ones: a reporter on #27 had seven. prune keeps every runtime
something still needs -- the newest (what a launch uses when nothing pins one), any a menu entry pins, the newest one
a prefix's stamp matches (what Mud Hut and `prefix provision` pick for it), any a process is running from, and every
folder that is not a numeric release -- and removes the rest, plus downloads that never finished.

`neutron uninstall` (DECISIONS C17: "downloads/caches (incl. Mud Hut's)") left Mud Hut's download cache, several GB
per app version, and its tools folder. It now removes both, and refuses while Mud Hut is installing or updating.

Run:  python3 tests/test_runtime_prune_and_uninstall.py
"""
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

_CLI = os.environ.get("NEUTRON_TEST_CLI") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli(env):
    with mock.patch.dict(os.environ, env):
        os.environ.pop("NEUTRON_WINE_VERSION", None)
        os.environ.pop("NEUTRON_WINE", None)
        spec = importlib.util.spec_from_loader(
            "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


class FakeHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="neutron-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = {"HOME": self.home, "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                    "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_CACHE_HOME": os.path.join(self.home, ".cache")}
        self.cli = _load_cli(self.env)
        self.rt = self.cli.NEUTRON_RUNTIMES_DIR
        self.procs = []
        self.addCleanup(self.stop_procs)

    def stop_procs(self):
        for p in self.procs:
            p.kill()
            p.wait()

    def runtime(self, name, stamp):
        root = os.path.join(self.rt, name)
        os.makedirs(os.path.join(root, "bin"))
        os.makedirs(os.path.join(root, "share", "wine"))
        with open(os.path.join(root, "bin", "wine"), "w") as f:
            f.write("#!/bin/sh\n")
        inf = os.path.join(root, "share", "wine", "wine.inf")
        open(inf, "w").close()
        os.utime(inf, (stamp, stamp))
        with open(os.path.join(root, "payload"), "wb") as f:
            f.write(b"\0" * 65536)
        return root

    def prefix(self, name, stamp, record=True):
        p = os.path.join(self.home, name)
        os.makedirs(os.path.join(p, "drive_c"))
        with open(os.path.join(p, ".update-timestamp"), "w") as f:
            f.write("%d\r\n" % stamp)
        if record:
            path = self.cli.NEUTRON_PREFIXES_JSON
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                with open(path) as f:
                    d = json.load(f)
            except OSError:
                d = {"prefixes": []}
            d["prefixes"].append(p)
            with open(path, "w") as f:
                json.dump(d, f)
        return p

    def menu_entry(self, prefix, version):
        os.makedirs(self.cli.APPS_DIR, exist_ok=True)
        with open(os.path.join(self.cli.APPS_DIR, "neutron-photoshop-x.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Photoshop\nExec=env %s neutron launch photoshop --prefix %s %%f\n"
                    % (self.cli.desktop_exec_arg("NEUTRON_WINE_VERSION=" + version), self.cli.desktop_exec_arg(prefix)))

    def call(self, *argv):
        args = self.cli.build_parser().parse_args(list(argv))
        buf = io.StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(buf):
            os.environ.pop("NEUTRON_WINE_VERSION", None)
            try:
                rc = args.func(args)
            except SystemExit as e:
                rc = e.code
        return rc, buf.getvalue()


class Prune(FakeHome):
    def setup_machine(self):
        self.runtime("neutron-wine-11.10-150", 1000)      # pinned by a menu entry
        self.runtime("neutron-wine-11.10-151", 2000)      # the stamp of a prefix with no menu entries
        self.runtime("neutron-wine-11.10-152", 3000)      # nothing uses it
        self.runtime("neutron-wine-11.10-153", 4000)      # newest
        self.runtime("neutron-wine-11.10-perf-test", 5000)  # a dev build: never touched
        old = os.path.join(self.rt, ".dl-abc123")         # a download that never finished
        os.makedirs(old)
        os.utime(old, (time.time() - 3 * 86400,) * 2)
        menu_prefix = self.prefix("My Prefixes/With Menu", 1000)
        self.menu_entry(menu_prefix, "11.10-150")
        self.prefix("NoMenu", 2000)

    def test_list_says_what_needs_each_runtime(self):
        self.setup_machine()
        rc, text = self.call("--json", "runtime", "list")
        self.assertEqual(rc, 0)
        rs = {r["version"] or r["name"]: r for r in json.loads(text)["runtimes"]}
        self.assertEqual(rs["11.10-153"]["used_by"], ["newest"])
        self.assertTrue(rs["11.10-150"]["used_by"][0].startswith("menu entries for ~/My Prefixes/With Menu"))
        self.assertEqual(rs["11.10-151"]["used_by"], ["prefix ~/NoMenu"])
        self.assertEqual(rs["11.10-152"]["used_by"], [])
        self.assertEqual(rs[".dl-abc123"]["used_by"], [])
        self.assertTrue(rs["11.10-perf-test"]["used_by"])

    def test_prune_removes_only_what_nothing_uses(self):
        self.setup_machine()
        rc, text = self.call("--json", "runtime", "prune", "--yes")
        self.assertEqual(rc, 0, text)
        self.assertEqual(sorted(os.listdir(self.rt)),
                         ["neutron-wine-11.10-150", "neutron-wine-11.10-151", "neutron-wine-11.10-153",
                          "neutron-wine-11.10-perf-test"])
        self.assertGreater(json.loads(text)["freed_bytes"], 0)

    def test_prune_asks_first(self):
        self.setup_machine()
        rc, text = self.call("--json", "runtime", "prune")
        self.assertNotEqual(rc, 0)
        self.assertIn("neutron-wine-11.10-152", text)
        self.assertTrue(os.path.isdir(os.path.join(self.rt, "neutron-wine-11.10-152")))

    def test_a_runtime_something_runs_from_is_kept(self):
        self.setup_machine()
        exe = os.path.join(self.rt, "neutron-wine-11.10-152", "bin", "sleep")
        shutil.copy("/bin/sleep", exe)
        self.procs.append(subprocess.Popen([exe, "60"]))
        time.sleep(0.2)
        rc, text = self.call("--json", "runtime", "prune", "--yes")
        self.assertEqual(rc, 0, text)
        self.assertTrue(os.path.isdir(os.path.join(self.rt, "neutron-wine-11.10-152")))

    def test_a_recent_unfinished_download_is_kept(self):
        os.makedirs(os.path.join(self.rt, ".dl-now"))
        self.runtime("neutron-wine-11.10-153", 4000)
        self.call("--json", "runtime", "prune", "--yes")
        self.assertTrue(os.path.isdir(os.path.join(self.rt, ".dl-now")))


class Uninstall(FakeHome):
    def test_mudhut_cache_and_tools_are_removed(self):
        cache = os.path.join(self.env["XDG_CACHE_HOME"], "mudhut", "AME-26.5.2.2-win64")
        os.makedirs(cache)
        tools = os.path.join(self.cli.NEUTRON_DATA_DIR, "mudhut-tools")
        os.makedirs(tools)
        rc, text = self.call("--json", "uninstall")           # no --yes: the plan, nothing removed
        plan = json.loads(text)["remove"]
        self.assertIn(os.path.join(self.env["XDG_CACHE_HOME"], "mudhut"), plan)
        self.assertIn(tools, plan)
        self.assertTrue(os.path.isdir(cache))

    def test_refused_while_mudhut_works_in_a_prefix(self):
        p = self.prefix("Adobe", 4000)
        os.makedirs(os.path.join(p, ".mudhut"))
        with open(os.path.join(p, ".mudhut", "state.json"), "w") as f:
            json.dump({"in_progress": {"pid": 1, "command": "install", "apps": ["photoshop"]}}, f)
        fd = os.open(os.path.join(p, ".mudhut", "lock"), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        rc, text = self.call("--json", "uninstall", "--yes")
        self.assertEqual(rc, self.cli.EX_RUNNING, text)
        self.assertIn("Mud Hut is working", json.loads(text)["reason"])


if __name__ == "__main__":
    unittest.main()
