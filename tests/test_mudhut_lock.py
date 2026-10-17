#!/usr/bin/env python3
"""Tests for the CLI side of Adobe app updates (2026-10-16):

  * `mudhut_busy`: Mud Hut's per-prefix flock `<prefix>/.mudhut/lock` read without creating it;
  * `neutron launch` refuses (exit 3, plain message) while Mud Hut holds it;
  * `neutron update` skips re-provisioning a prefix Mud Hut holds;
  * `neutron --json prefix list` (Mud Hut's `check-updates --all-prefixes` reads it);
  * `_resolve_app_exe` starts the NEWEST year installed, reading the year from the app folder,
    not the prefix path; `_running_app_ids` sees every installed year.

Nothing here starts wine: "processes" are `sleep`/`flock` children with a chosen WINEPREFIX and a
Windows-style argv[0], as in test_identity.py.

Run:  python3 tests/test_mudhut_lock.py
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli_lock", importlib.machinery.SourceFileLoader("neutron_cli_lock", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()


def _prefix(root, name="pfx"):
    p = os.path.join(root, name)
    os.makedirs(os.path.join(p, "drive_c", "Program Files", "Adobe"), exist_ok=True)
    return p


def _hold_lock(prefix, state=None):
    d = os.path.join(prefix, ".mudhut")
    os.makedirs(d, exist_ok=True)
    if state is not None:
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"schema": 1, "in_progress": state}, f)
    lock = os.path.join(d, "lock")
    open(lock, "a").close()
    # -o: `sleep` does not inherit the lock fd, so killing flock frees it.
    child = subprocess.Popen(["flock", "-o", lock, "sleep", "30"])
    for _ in range(50):
        if N.mudhut_busy(prefix) is not None:
            break
        time.sleep(0.05)
    return child


class MudhutLock(unittest.TestCase):
    def test_no_lock_file_is_not_busy_and_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t)
            self.assertIsNone(N.mudhut_busy(p))
            self.assertFalse(os.path.exists(os.path.join(p, ".mudhut")), "must never create .mudhut")

    def test_held_lock_reports_the_running_job_and_is_released_with_the_holder(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t)
            child = _hold_lock(p, {"pid": 1, "command": "update", "apps": ["photoshop"]})
            try:
                info = N.mudhut_busy(p)
                self.assertEqual(info["apps"], ["photoshop"])
                self.assertIn("Photoshop", N._mudhut_busy_sentence(info))
            finally:
                child.kill()
                child.wait()
            time.sleep(0.1)
            self.assertIsNone(N.mudhut_busy(p), "a dead holder leaves no lock")

    def test_an_unlocked_stale_file_is_not_busy(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t)
            os.makedirs(os.path.join(p, ".mudhut"))
            open(os.path.join(p, ".mudhut", "lock"), "w").write("123 update 2026\n")
            self.assertIsNone(N.mudhut_busy(p))

    def test_launch_refuses_with_exit_3_while_locked(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t)
            child = _hold_lock(p, {"pid": 1, "command": "update", "apps": ["photoshop"]})
            try:
                env = dict(os.environ, HOME=t, XDG_DATA_HOME=os.path.join(t, "share"),
                           XDG_CONFIG_HOME=os.path.join(t, "config"))
                r = subprocess.run([sys.executable, _CLI, "--json", "launch", "photoshop", "--prefix", p],
                                   capture_output=True, text=True, env=env, timeout=60)
            finally:
                child.kill()
                child.wait()
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            out = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertFalse(out["launched"])
            self.assertIn("being updated", out["reason"])

    def test_update_skips_a_locked_prefix(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t)
            child = _hold_lock(p, {"pid": 1, "command": "update", "apps": ["premiere"]})
            saved = (N.neutron_prefixes, N.stamp_mismatch, N._running_app_ids, subprocess.run)
            calls = []
            try:
                N.neutron_prefixes = lambda: [p]
                N.stamp_mismatch = lambda *_a, **_k: {"prefix_runtimes": []}
                N._running_app_ids = lambda _p: []
                N.subprocess.run = lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0)
                step = N._reprovision_prefixes("11.10-999", True)
            finally:
                N.neutron_prefixes, N.stamp_mismatch, N._running_app_ids, N.subprocess.run = saved
                child.kill()
                child.wait()
            self.assertEqual(calls, [], "a locked prefix must not be provisioned")
            self.assertEqual(step["skipped"][0]["prefix"], p)
            self.assertIn("Mud Hut update", step["skipped"][0]["running"][0])


class PrefixList(unittest.TestCase):
    def test_lists_recorded_and_menu_prefixes(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = _prefix(t, "a"), _prefix(t, "b")
            data = os.path.join(t, "share")
            os.makedirs(os.path.join(data, "neutron"))
            os.makedirs(os.path.join(data, "applications"))
            json.dump({"prefixes": [a, os.path.join(t, "gone")]}, open(os.path.join(data, "neutron", "prefixes.json"), "w"))
            open(os.path.join(data, "applications", "neutron-photoshop-b.desktop"), "w").write(
                "[Desktop Entry]\nExec=neutron launch photoshop --prefix %s\n" % b)
            env = dict(os.environ, HOME=t, XDG_DATA_HOME=data)
            r = subprocess.run([sys.executable, _CLI, "--json", "prefix", "list"], capture_output=True,
                               text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = {e["path"]: e for e in json.loads(r.stdout)["prefixes"]}
            self.assertTrue(got[os.path.realpath(a)]["valid"] and got[os.path.realpath(a)]["recorded"])
            self.assertEqual(got[os.path.realpath(b)]["menu_entries"], 1)
            self.assertFalse(got[os.path.realpath(os.path.join(t, "gone"))]["valid"])


class Years(unittest.TestCase):
    def _app(self, p, year):
        d = os.path.join(p, "drive_c", "Program Files", "Adobe", "Adobe Photoshop %d" % year)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "Photoshop.exe"), "w").write("MZ")
        return os.path.join(d, "Photoshop.exe")

    def test_newest_year_wins_even_over_the_pinned_literal(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t, "Adobe2027")  # a year in the PREFIX name must not decide
            pinned = self._app(p, 2025)
            new = self._app(p, 2026)
            rel = os.path.relpath(pinned, p)
            self.assertEqual(N._resolve_app_exe(p, rel), new)

    def test_a_running_older_year_counts_as_running(self):
        with tempfile.TemporaryDirectory() as t:
            p = _prefix(t)
            self._app(p, 2025)
            self._app(p, 2026)
            argv0 = "C:\\Program Files\\Adobe\\Adobe Photoshop 2025\\Photoshop.exe"
            child = subprocess.Popen(["sh", "-c", "exec -a '%s' sleep 30" % argv0], env=dict(os.environ, WINEPREFIX=p))
            try:
                time.sleep(0.3)
                self.assertIn("photoshop", N._running_app_ids(p))
            finally:
                child.kill()
                child.wait()


if __name__ == "__main__":
    unittest.main()
