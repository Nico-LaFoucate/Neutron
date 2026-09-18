#!/usr/bin/env python3
"""Tests for the per-app-PER-PREFIX identity fixes in bin/neutron (2026-09-18).

The bug class: an identifier that is per-app where it must be per-app-per-prefix. With the same
Adobe app installed in two prefixes (Premiere 2025 in ~/.premiere2025, Premiere 2026 in
~/Neutron-Prefixes/Adobe2026) every one of these attributed one prefix's state to the other:

  * `_prefix_procs` substring-matched `WINEPREFIX=<prefix>` against the joined environ, so
    ~/mudhut-accc owned ~/mudhut-accc2's processes.
  * `premiere_is_running()` scanned all of /proc with no prefix check, so `apply-display-fix`
    refused (exit 3) for a prefix in which nothing was running.
  * launch logs were `<app>-<ts>.log` and pruned 20-per-app ACROSS prefixes.
  * `repair_mime_defaults` repaired dangling claims only for the types WE declare, so a retired
    `mudhut-<app>.desktop` stayed the default for Mud Hut's own types forever.

Every test here is validated against a KNOWN-BAD state: each one was run against the pre-fix
code and failed there (see the commit message for the run). The "processes" are `sleep` children
started with a chosen WINEPREFIX and, where the test needs it, a Windows-style argv[0] -- exactly
what wine leaves in /proc/<pid>/cmdline[0] -- so nothing here starts wine or touches a prefix.

Run:  python3 tests/test_identity.py
"""
import configparser
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "neutron")


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "neutron_cli", importlib.machinery.SourceFileLoader("neutron_cli", _CLI))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load_cli()

# What wine puts in /proc/<pid>/cmdline[0] for Premiere: the WINDOWS path of the exe.
PREMIERE_ARGV0 = r"C:\Program Files\Adobe\Adobe Premiere Pro 2025\Adobe Premiere Pro.exe"


def _spawn(test, wineprefix, argv0="sleep"):
    """A live process carrying WINEPREFIX=<wineprefix> in its environ, with the given argv[0].
    Killed at test teardown."""
    env = dict(os.environ, WINEPREFIX=wineprefix)
    p = subprocess.Popen([argv0, "60"], executable="/usr/bin/sleep", env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _reap():
        p.kill()
        p.wait()
    test.addCleanup(_reap)
    # /proc/<pid>/environ is readable immediately after exec; give exec a moment anyway.
    for _ in range(50):
        try:
            with open("/proc/%d/cmdline" % p.pid, "rb") as f:
                if f.read().split(b"\0")[0].decode("utf-8", "replace") == argv0:
                    break
        except OSError:
            pass
        time.sleep(0.01)
    return p.pid


def _fake_premiere_prefix(root, name):
    """A prefix containing only Premiere's exe path, enough for _resolve_app_exe to bind."""
    prefix = os.path.join(root, name)
    exe = os.path.join(prefix, N.PREMIERE_SUBPATH)
    os.makedirs(os.path.dirname(exe))
    open(exe, "wb").close()
    return prefix


class PrefixProcs(unittest.TestCase):
    """`_prefix_procs` must compare WINEPREFIX as a WHOLE environ entry."""

    def test_sibling_prefix_with_common_stem_is_not_matched(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "mudhut-accc")
            b = os.path.join(tmp, "mudhut-accc2")
            pid = _spawn(self, b)
            self.assertIn(pid, {p for p, _c, _a in N._prefix_procs(b)},
                          "the process's own prefix must see it")
            self.assertNotIn(pid, {p for p, _c, _a in N._prefix_procs(a)},
                             "a prefix whose path is a PREFIX of the real one must not see it")

    def test_trailing_slash_is_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = os.path.join(tmp, "p")
            pid = _spawn(self, b)
            self.assertIn(pid, {p for p, _c, _a in N._prefix_procs(b + "/")})


class PremiereIsRunning(unittest.TestCase):
    """`premiere_is_running(prefix)` must answer for THIS prefix only."""

    def test_other_prefix_is_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            p2025 = _fake_premiere_prefix(tmp, "premiere2025")
            p2026 = _fake_premiere_prefix(tmp, "Adobe2026")
            _spawn(self, p2025, PREMIERE_ARGV0)
            self.assertTrue(N.premiere_is_running(p2025),
                            "Premiere IS running in this prefix")
            self.assertFalse(N.premiere_is_running(p2026),
                             "nothing is running in the other prefix -- the old global /proc "
                             "scan said True here and apply-display-fix refused with exit 3")

    def test_nothing_running_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _fake_premiere_prefix(tmp, "quiet")
            self.assertFalse(N.premiere_is_running(p))


class PruneAppLogs(unittest.TestCase):
    """Logs are `<app>-<prefix slug>-<ts>.log`, pruned per app AND prefix."""

    def _mk(self, d, name, age):
        p = os.path.join(d, name)
        open(p, "wb").close()
        os.utime(p, (time.time() - age, time.time() - age))
        return p

    def test_busy_prefix_does_not_prune_quiet_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            busy = [self._mk(d, "premiere-premiere2025-%03d.log" % i, 1000 - i) for i in range(30)]
            quiet = [self._mk(d, "premiere-adobe2026-%03d.log" % i, 5000 - i) for i in range(3)]
            other = self._mk(d, "photoshop-premiere2025-000.log", 9000)
            N._prune_app_logs(d, "premiere", "premiere2025", keep=20)
            left = set(os.listdir(d))
            self.assertTrue(all(os.path.basename(q) in left for q in quiet),
                            "the quiet prefix's history must survive the busy one's prune")
            self.assertIn(os.path.basename(other), left)
            kept_busy = [b for b in busy if os.path.basename(b) in left]
            self.assertEqual(len(kept_busy), 19, "keep-1: one more is about to be created")
            # The NEWEST survive (age 1000-i: higher i = newer).
            self.assertEqual(sorted(os.path.basename(b) for b in kept_busy),
                             ["premiere-premiere2025-%03d.log" % i for i in range(11, 30)])


class RepairMimeDefaults(unittest.TestCase):
    """A dangling `mudhut-<app>.desktop` claim is re-pointed at the app's new entry, for ANY
    type -- but a live claim is never stolen."""

    MIMEAPPS = (
        "[Added Associations]\n"
        "text/plain=org.kde.kate.desktop;\n"
        "\n"
        "[Default Applications]\n"
        "text/plain=org.kde.kate.desktop\n"
        "image/vnd.adobe.photoshop=neutron-photoshop-premiere2025.desktop\n"
        "application/vnd.adobe.premiere-project=mudhut-premiere.desktop\n"
        "application/vnd.adobe.aftereffects.project=mudhut-aftereffects.desktop\n"
        "application/x-neutron-prproj=neutron-premiere-premiere2025.desktop\n"
    )

    def _home(self, tmp, live_entries):
        home = os.path.join(tmp, "home")
        apps = os.path.join(home, ".local", "share", "applications")
        os.makedirs(apps)
        os.makedirs(os.path.join(home, ".config"))
        with open(os.path.join(home, ".config", "mimeapps.list"), "w") as f:
            f.write(self.MIMEAPPS)
        for e in live_entries:
            open(os.path.join(apps, e), "w").close()
        return home, apps

    def _defaults(self, home):
        cp = configparser.RawConfigParser()
        cp.optionxform = str
        cp.read(os.path.join(home, ".config", "mimeapps.list"))
        return dict(cp.items("Default Applications"))

    def test_dead_mudhut_claim_is_repointed_only_for_the_app_we_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, apps = self._home(tmp, ["neutron-premiere-premiere2025.desktop",
                                          "neutron-photoshop-premiere2025.desktop",
                                          "neutron-premiere-adobe2026.desktop"])
            old_home = N.HOME
            N.HOME = home
            try:
                claimed = N.repair_mime_defaults(apps, [
                    {"app": "premiere", "mime": ["application/x-neutron-prproj"],
                     "file": "neutron-premiere-adobe2026.desktop"}])
            finally:
                N.HOME = old_home
            d = self._defaults(home)
            self.assertEqual(d["application/vnd.adobe.premiere-project"],
                             "neutron-premiere-adobe2026.desktop",
                             "dead mudhut-premiere claim -> the premiere entry we just wrote")
            self.assertIn("application/vnd.adobe.premiere-project", claimed)
            self.assertEqual(d["application/vnd.adobe.aftereffects.project"],
                             "mudhut-aftereffects.desktop",
                             "we wrote no aftereffects entry this run -- not ours to touch")
            self.assertEqual(d["application/x-neutron-prproj"],
                             "neutron-premiere-premiere2025.desktop",
                             "a LIVE claim by the other prefix's entry is never stolen")
            self.assertEqual(d["image/vnd.adobe.photoshop"],
                             "neutron-photoshop-premiere2025.desktop")
            self.assertEqual(d["text/plain"], "org.kde.kate.desktop")

    def test_live_mudhut_claim_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, apps = self._home(tmp, ["neutron-premiere-adobe2026.desktop",
                                          "mudhut-premiere.desktop"])
            old_home = N.HOME
            N.HOME = home
            try:
                N.repair_mime_defaults(apps, [
                    {"app": "premiere", "mime": ["application/x-neutron-prproj"],
                     "file": "neutron-premiere-adobe2026.desktop"}])
            finally:
                N.HOME = old_home
            d = self._defaults(home)
            self.assertEqual(d["application/vnd.adobe.premiere-project"],
                             "mudhut-premiere.desktop")
            # The dangling x-neutron-prproj claim (its entry does not exist here) IS ours.
            self.assertEqual(d["application/x-neutron-prproj"],
                             "neutron-premiere-adobe2026.desktop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
