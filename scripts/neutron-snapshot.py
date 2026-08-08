#!/usr/bin/env python3
"""neutron-snapshot.py — dump the state of a Neutron prefix + runtime + host, diffably.

WHY THIS EXISTS
---------------
"Works on the dev box, fails on yours" burned a full day of build testing in 2026-08. Every
theory was argued from logs when the real question was simply: what does a WORKING install have
that a broken one doesn't? This answers that mechanically.

  dev box:      neutron-snapshot.py --prefix ~/.premiere2025 > healthy.txt
  tester:       neutron-snapshot.py --prefix ~/Neutron/Adobe > mine.txt
  either:       diff healthy.txt mine.txt

Output is deliberately diff-friendly: sorted, no timestamps, and usernames/home paths normalised
to <HOME>/<USER> so two machines produce identical lines for identical state.

Sizes, not hashes: patched Wine natives differ per build, and a size mismatch is the signal that
matters (a clobbered dwrite is 508105 vs a patched 520470). Hashes would flag every legitimate
build difference as noise.

Reads only. Never writes to the prefix. Safe to run while apps are open.
"""
import argparse, json, os, re, subprocess, sys

HOME = os.path.expanduser("~")
USER = os.path.basename(HOME)


def norm(s):
    """Normalise machine-specific text so two machines diff cleanly."""
    if not isinstance(s, str):
        return s
    s = s.replace(HOME, "<HOME>")
    return re.sub(rf"\b{re.escape(USER)}\b", "<USER>", s)


def out(label, value):
    print(f"{label:<44} {norm(str(value))}")


def size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return "MISSING"


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return f"<failed: {e}>"


def section(title):
    print()
    print(f"===== {title} " + "=" * max(0, 60 - len(title)))


# --------------------------------------------------------------------------- host
def host():
    section("HOST")
    gpu = run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    out("gpu", gpu.splitlines()[0] if gpu and "failed" not in gpu else gpu)
    try:
        pretty = [l for l in open("/etc/os-release") if l.startswith("PRETTY_NAME")]
        out("distro", pretty[0].split("=", 1)[1].strip().strip('"') if pretty else "?")
    except OSError:
        out("distro", "?")
    out("session", f"{os.environ.get('XDG_SESSION_TYPE','?')} / {os.environ.get('XDG_CURRENT_DESKTOP','?')}")
    out("python3", sys.version.split()[0])
    # A distro wine on PATH is NOT required — Neutron ships its own. Recorded because its
    # presence/absence changed the behaviour of `doctor` (see the 2026-08-08 incident).
    out("system-wine-on-PATH", run(["which", "wine"]) or "<none>")


# ------------------------------------------------------------------------- runtime
def runtime():
    section("RUNTIME")
    base = os.path.join(HOME, ".local/share/neutron/runtimes")
    rts = sorted(os.listdir(base)) if os.path.isdir(base) else []
    # Only detail the ACTIVE runtime. A dev box accumulates dozens; a tester has one, so listing
    # them all would bury the real differences under 40 spurious diff lines.
    active = os.environ.get("NEUTRON_WINE_VERSION")
    if not active:
        try:
            src = open(os.path.join(HOME, "neutron/bin/neutron"), encoding="utf-8").read()
            m = re.search(r'NEUTRON_WINE_VERSION["\']?\s*,\s*["\']([^"\']+)', src)
            active = m.group(1) if m else None
        except OSError:
            active = None
    out("runtimes-installed", f"{len(rts)} (detailing the active one only)")
    out("runtime-ACTIVE", active or "<unresolved>")
    rts = [r for r in rts if active and r.endswith(active)] or rts[-1:]
    for rt in rts:
        d = os.path.join(base, rt)
        marker = os.path.join(d, "NEUTRON_WINE_VERSION")
        ver = open(marker).read().strip() if os.path.isfile(marker) else "?"
        out(f"  {rt}/VERSION", ver)
        for sub in ("share/wine/mono", "share/wine/gecko"):
            p = os.path.join(d, sub)
            n = len(os.listdir(p)) if os.path.isdir(p) else 0
            out(f"  {rt}/{sub}", f"{n} entries" if n else "MISSING (Mono/Gecko popup risk)")
        # The patched natives the runtime ships, by size.
        for arch, names in (("x86_64-windows", ("dxcore.dll", "dcomp.dll", "dwrite.dll")),
                            ("i386-windows", ("dxcore.dll", "dcomp.dll"))):
            for n in names:
                out(f"  {rt}/lib/wine/{arch}/{n}", size(os.path.join(d, "lib/wine", arch, n)))

    section("RUNTIME DLL BUNDLE (what `prefix provision` stages)")
    b = os.path.join(HOME, "neutron/runtime")
    out("bundle-present", os.path.isdir(b))
    if os.path.isdir(b):
        for sub in ("dlls/system32", "dlls/syswow64", "mono", "gecko", "webview2"):
            p = os.path.join(b, sub)
            out(f"  {sub}", f"{len(os.listdir(p))} entries" if os.path.isdir(p) else "MISSING")
        ov = os.path.join(b, "overrides.json")
        if os.path.isfile(ov):
            try:
                out("  overrides.json", f"{len(json.load(open(ov)))} entries")
            except Exception as e:
                out("  overrides.json", f"<unreadable: {e}>")

    section("MUD HUT")
    mh = run(["which", "mudhut"])
    out("mudhut-on-PATH", mh or "<none>")
    if mh:
        real = os.path.realpath(mh)
        out("mudhut-real-path", real)
        tools = os.path.join(os.path.dirname(real), "tools")
        # Without these, download/offline installs cannot stage Adobe's Desktop Common runtime.
        for t in ("hdpim_host.exe", "extract_accc_runtime.py"):
            out(f"  tools/{t}", "present" if os.path.isfile(os.path.join(tools, t)) else "MISSING")


# -------------------------------------------------------------------------- prefix
def prefix_report(p):
    section(f"PREFIX  {norm(p)}")
    if not os.path.isdir(os.path.join(p, "drive_c")):
        out("valid", "NO — no drive_c")
        return
    out("valid", "yes")
    stamp = os.path.join(p, ".update-timestamp")
    out("stamp", open(stamp).read().strip() if os.path.isfile(stamp) else "MISSING")

    section("PREFIX · installed Adobe apps")
    ad = os.path.join(p, "drive_c/Program Files/Adobe")
    apps = sorted(d for d in os.listdir(ad)) if os.path.isdir(ad) else []
    for a in apps:
        out(f"  {a}", "")
    if not apps:
        out("  <none>", "")

    section("PREFIX · Adobe Desktop Common (CC-desktop runtime; Photoshop needs the broker)")
    adc = os.path.join(p, "drive_c/Program Files (x86)/Common Files/Adobe/Adobe Desktop Common")
    if os.path.isdir(adc):
        for d in sorted(os.listdir(adc)):
            out(f"  {d}", "")
    else:
        out("  <absent>", "Adobe Desktop Common not staged")
    broker = os.path.join(adc, "IPCBox/AdobeIPCBroker.exe")
    out("AdobeIPCBroker.exe", "present" if os.path.isfile(broker) else "MISSING (Photoshop will fail)")

    section("PREFIX · native DLLs (size; a MISMATCH vs the healthy box is the signal)")
    for rel in ("system32/dxcore.dll", "syswow64/dxcore.dll",
                "system32/dcomp.dll", "syswow64/dcomp.dll",
                "system32/dwrite.dll", "system32/d3d11.dll", "system32/dxgi.dll",
                "system32/d3d12core.dll", "system32/ucrtbase.dll",
                "system32/ucrtbase_orig.dll", "system32/nvapi64.dll"):
        f = os.path.join(p, "drive_c/windows", rel)
        s = size(f)
        if os.path.islink(f):
            s = f"{s} (symlink -> {norm(os.path.realpath(f))})"
        out(f"  {rel}", s)

    section("PREFIX · DLL overrides (HKCU\\Software\\Wine\\DllOverrides)")
    try:
        reg = open(os.path.join(p, "user.reg"), encoding="utf-8", errors="replace").read()
        m = re.search(r'\[Software\\\\Wine\\\\DllOverrides\](.*?)(\n\[|\Z)', reg, re.S)
        ov = dict((st + n, v) for st, n, v in
                  re.findall(r'"(\*?)([^"]+)"="([^"]+)"', m.group(1))) if m else {}
        out("count", len(ov))
        for k in sorted(ov):
            out(f"  {k}", ov[k])
    except OSError as e:
        out("user.reg", f"<unreadable: {e}>")

    section("PREFIX · fonts")
    fd = os.path.join(p, "drive_c/windows/Fonts")
    fonts = sorted(os.listdir(fd)) if os.path.isdir(fd) else []
    out("font-count", len(fonts))
    clean = [f for f in fonts if "adobeclean" in f.lower()]
    # Adobe Clean backs the Segoe UI replacement provision writes. Missing => the replacement
    # resolves to an unregistered family. `--method windows` never seeds it (Mud Hut's
    # seed_ui_fonts runs only on the download/offline paths).
    out("AdobeClean-registered", f"{len(clean)} files" if clean else "MISSING")
    try:
        reg = open(os.path.join(p, "user.reg"), encoding="utf-8", errors="replace").read()
        m = re.search(r'\[Software\\\\Wine\\\\Fonts\\\\Replacements\](.*?)(\n\[|\Z)', reg, re.S)
        reps = re.findall(r'"([^"]+)"="([^"]+)"', m.group(1)) if m else []
        out("font-replacements", len(reps))
        for k, v in sorted(reps)[:6]:
            out(f"  {k}", v)
    except OSError:
        pass

    section("PREFIX · DXVK configs (launch exports DXVK_CONFIG_FILE with no existence check)")
    confs = {"neutron-apps-dxvk.conf": "shared (PS/LrC/Animate/AME/Illustrator)",
             "neutron-ae-dxvk.conf": "After Effects"}
    for name, who in confs.items():
        f = os.path.join(p, name)
        out(f"  {name}", f"{size(f)} bytes — {who}" if os.path.isfile(f) else f"MISSING — {who}")
    for app in apps:
        f = os.path.join(ad, app, "dxvk.conf")
        if os.path.isfile(f):
            keys = [l.split("=")[0].strip() for l in open(f, errors="replace")
                    if "=" in l and not l.strip().startswith("#")]
            out(f"  {app}/dxvk.conf", f"{size(f)} bytes, keys: {', '.join(sorted(keys))}")

    section("PREFIX · Premiere Debug Database (display fix)")
    base = os.path.join(p, "drive_c/users", USER, "AppData/Roaming/Adobe")
    found = False
    for app_dir in ("Premiere Pro", "After Effects", "Adobe Media Encoder"):
        d = os.path.join(base, app_dir)
        if not os.path.isdir(d):
            continue
        for ver in sorted(os.listdir(d)):
            f = os.path.join(d, ver, "Debug Database.txt")
            if os.path.isfile(f):
                found = True
                val = "<key absent>"
                for ln in open(f, errors="replace"):
                    if ln.startswith("DS.DisableDirectXDisplay"):
                        val = ln.strip().split("\t")[1] if "\t" in ln else "?"
                out(f"  {app_dir}/{ver}", f"DS.DisableDirectXDisplay = {val}")
    if not found:
        out("  <none>", "no Debug Database yet (written on an app's first successful launch)")


def main():
    ap = argparse.ArgumentParser(description="Diffable snapshot of a Neutron install.")
    ap.add_argument("--prefix", help="prefix to inspect (default: Collider's selected prefix)")
    a = ap.parse_args()

    p = a.prefix
    if not p:
        try:
            cfg = json.load(open(os.path.join(HOME, ".config/collider/config.json")))
            p = cfg.get("selected_prefix")
        except Exception:
            p = None
    print("NEUTRON SNAPSHOT — compare with `diff healthy.txt mine.txt`")
    print("(paths normalised to <HOME>/<USER>; sizes not hashes; read-only)")
    host()
    runtime()
    if p:
        prefix_report(os.path.expanduser(p))
    else:
        section("PREFIX")
        out("prefix", "NOT RESOLVED — pass --prefix")

    # Normalised like everything else — an un-normalised path here would diff on every line.
    section("DOCTOR")
    print(norm(run(["neutron", "--json", "doctor", "--prefix", p]) if p
               else run(["neutron", "--json", "doctor"])))
    section("MUDHUT DOCTOR")
    print(norm(run(["mudhut", "doctor"])))


if __name__ == "__main__":
    main()
