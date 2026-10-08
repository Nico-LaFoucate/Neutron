<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/neutron-logo-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/neutron-logo-light.png">
  <img src="assets/neutron-logo-light.png" alt="Neutron" width="150">
</picture>

# Neutron

**A Wine-based compatibility engine tuned for professional creative software on Linux.**

Premiere Pro · After Effects · Photoshop · Lightroom · Illustrator · Animate · Media Encoder
— accelerated on your GPU, running on Linux.

<br>

![Status](https://img.shields.io/badge/status-beta-2BB673)
![Platform](https://img.shields.io/badge/platform-Linux-informational)
![Built on Wine](https://img.shields.io/badge/built_on-Wine-8A2BE2)
![GPU](https://img.shields.io/badge/GPU-Vulkan_·_CUDA_·_NVENC-76B900)
![License](https://img.shields.io/badge/license-LGPL_2.1+-blue)

</div>

---

> [!WARNING]
> **Neutron is in beta.** The applications below are used for real work — including paid client
> work — and are tested on three machines, all CachyOS with KDE Plasma (Wayland) and NVIDIA GPUs.
> AMD and Intel GPUs, other distributions and other desktops aren't validated yet. Things break,
> and you must bring your own legally licensed Adobe software.

---

## What is Neutron?

Linux is already a first-class platform for gaming, development, and infrastructure — but
professional content creators are still tethered to Windows and macOS by the deep OS
dependencies of industry-standard creative tools.

**Neutron aims to close that gap.** Just as Valve's Proton tailored Wine to make Windows games
run near-natively on Linux, Neutron forks and tunes Wine specifically for the demands of
professional creative software: high-throughput media pipelines, GPU compute, color management,
licensing daemons, and the tangle of inter-process communication these suites rely on.

The goal is simple to state and hard to reach: make Linux a rock-solid daily driver for
multimedia professionals.

Neutron is the **engine**. It is designed to be driven directly from its command line, or through
[**Collider**](#collider--the-companion-launcher), a graphical launcher and prefix manager built
on top of it.

---

## Architecture

Neutron sits between your creative applications and the Linux graphics stack, coordinating a
patched Wine foundation and shipping the fixes those applications need to run.

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/architecture-light.svg">
  <img src="assets/architecture-light.svg" alt="Neutron architecture: Adobe apps run on the Neutron engine, which drives a patched Wine + DXVK + vkd3d-proton foundation on top of the Linux graphics and compute stack." width="820">
</picture>

</div>

---

## Compatibility

> [!NOTE]
> These are results observed on the test machines described above, and every entry has rough
> edges. Tiers match the [status board](https://neutronproject.org), which is canonical:
>
> | Tier | Meaning |
> | :--- | :--- |
> | 🟢 `Beta` | Usable for real work |
> | 🟡 `Partial` | Launches, major gaps |
> | 🔵 `Likely` | Inherits fixes from another release, unverified |
> | 🔴 `Not working` | Confirmed broken |
> | ⚪ `Untested` | Assume broken |
>
> Support is tracked **per release** — a fix landing on one version does not automatically carry
> to the next.

| Application / Feature | Status | Notes |
| :--- | :--- | :--- |
| **Premiere Pro 2025** | 🟢 `Beta` | GPU/Mercury rendering, timeline playback, and hardware **NVENC** export that muxes natively into a valid MP4. Frame pacing and third-party plugins are still rough. |
| **After Effects 2025** | 🟢 `Beta` | Workspace, dialogs, and **composition rendering** (Wine's Direct2D was missing the un-premultiply effect AE treats as fatal). Rulers/guides overlay is disabled pending CUDA↔D3D11 interop. |
| **Photoshop 2025** | 🟢 `Beta` | Boots to the home screen; full workspace docks on **File → New**; GPU canvas drawing (~56 fps in testing). Some warm-up lag remains. |
| **Lightroom Classic** | 🟢 `Beta` | Imports 1000+ RAW files, SD-card hotplug, masking, AI Denoise, Edit-in-Photoshop. UI load-in is slow. |
| **Illustrator 2025** | 🟢 `Beta` | Artboard, panels and toolbars render correctly (a whole-window shear traced to `CreateBitmapIndirect` discarding the caller's stride). |
| **Media Encoder 2025** | 🟢 `Beta` | Queue, render and export end-to-end, including native muxing. |
| **Animate 2024** | 🟢 `Beta` | Canvas, panels and playback. Its home screen is blank — that is Adobe's own bug, blank on Windows too; File → New works. |
| **Dynamic Link** (Premiere ↔ After Effects) | 🟢 `Beta` | Full round trip, no engine changes required — both applications must be running. |
| **CEP / UXP panels** | 🟢 `Beta` | Third-party panels render and stay interactive inside their docks. |
| **Pen / tablet input** | 🟢 `Beta` | Pressure, tilt and eraser via WinTab, at the tablet's native resolution. The first-stroke stray is fixed — Wine's WinTab context declared `lcOutExt` in tablet units where a real Wacom declares screen pixels, a factor-of-UPP error in the mapping Photoshop uses before it calibrates. |
| **Drag and drop from the file manager** | 🟢 `Beta` | Dropping files from Dolphin/Nautilus into an application. |
| **NVIDIA (CUDA / NVENC)** | 🟢 `Beta` | The primary hardware used in development (RTX 5070, nvidia-open). |
| **AMD / Intel GPUs** | ⚪ `Untested` | Non-NVIDIA compute/present paths have not been validated. NVENC in particular is NVIDIA-only. |
| **Third-party plugins** | 🟢 `Beta` | In daily use: Captioneer and other third-party panels in Premiere Pro, and VST3 audio plugins in Premiere Pro. The aescripts + aeplugins manager runs; installing plugins through it hasn't been tested yet. |

### Creative Cloud 2026

The table above is the 2025 line; the 2026 line is below.

| Application | Status | Notes |
| :--- | :--- | :--- |
| **Premiere Pro 2026** | 🟢 `Beta` | Installed from an offline package and verified launching and running on the 2026 stack, inheriting the 2025 fixes with no new engine work. Not yet used for a paid job on this release. |
| **Photoshop 2026** | 🟢 `Beta` | Stable for day-to-day work on this release. |
| **After Effects 2026** | 🟢 `Beta` | Installed from an offline package; opens a project and the **composition viewer renders**. Needed a fix on our side — AE 2026 keeps two preference databases and `DS.DisableDirectXDisplay` was being written to the one it does not read. Not yet used for a paid job on this release. |
| **Illustrator 2026** | 🟢 `Beta` | Installs and runs on this release. Not yet used for a paid job on 2026. |
| **Media Encoder 2026** | 🟢 `Beta` | Installs and runs on this release. Not yet used for a paid job on 2026. |
| **Lightroom Classic 2026** | 🟢 `Beta` | Installs and runs on this release. |
| **Animate** | ⚪ `n/a` | Adobe has not shipped a 2026 Animate. The 2024 build is current and is covered under the 2025 line above. |

The 2026 apps above were installed with Mud Hut's **offline** method from a disc image. Dynamic
Link's prerequisites (Premiere + After Effects) both run on 2026, but the round trip has not been
exercised on this release yet.

The [status board](https://neutronproject.org) tracks both releases and is the canonical view.

> [!NOTE]
> Even where a specific app is untested, the core fixes built for the apps above — licensing and
> daemon isolation, GPU/compute mapping, font rendering, IPC, and native display/present paths —
> lay the groundwork for the rest of the Creative Cloud ecosystem.

---

## What Neutron actually does

Under the hood, Neutron is a set of targeted fixes and a runtime that assembles them. The main
focus areas:

- **🎨 Native display & present paths** — routing each application's on-screen surfaces through a
  path that actually works under Wine, so panels, canvases, and monitors render on the GPU.
- **⚡ GPU & compute mapping** — translating Windows compute APIs (D3D11/12, CUDA) into native
  Vulkan and `libcuda` for real-time effects, rendering, and export.
- **🔐 Licensing & daemon isolation** — keeping Adobe's own background licensing services running.
- **🔊 Low-latency audio** — routing through modern Linux audio (PipeWire) to avoid sync drift on
  heavy timelines.
- **🔗 Inter-process communication** — the structural foundation for interoperability between
  suite applications (dynamic asset linking, panels, brokers).
- **📦 Hardware export** — NVENC output muxed natively into valid deliverables. (This began as an
  external finalize daemon; it was retired once the underlying fault — Microsoft's UCRT rejecting
  Wine's `\\?\` temp paths, which made the muxer skip interleaving — was fixed properly.)

The engine's fixes live in [neutron-wine](https://github.com/Nico-LaFoucate/neutron-wine), the
patched Wine runtime.

---

## Getting Started

> [!IMPORTANT]
> Neutron is in beta. You need your own licensed Adobe apps. You sign in inside the Adobe app, the
> same as on Windows; Neutron never touches your Adobe account or login.

**Requirements**

- 64-bit Linux with glibc 2.39 or newer (Ubuntu 24.04, Fedora 40, current Arch / CachyOS /
  Manjaro, openSUSE Tumbleweed) and a **Wayland** session.
- An **NVIDIA GPU**. AMD and Intel GPUs are not validated yet.
- **Python 3** and **cabextract**.

**Install**

```bash
curl -LO https://github.com/Nico-LaFoucate/neutron/releases/latest/download/neutron
python3 neutron setup
```

`neutron setup` downloads [neutron-wine](https://github.com/Nico-LaFoucate/neutron-wine) and the
[Mud Hut](https://github.com/Nico-LaFoucate/Mud-Hut) installer from GitHub, Microsoft's Visual C++
runtimes, GDI+ and core fonts from Microsoft, and Adobe's Creative Cloud package from Adobe, and
installs [Collider](https://github.com/Nico-LaFoucate/Collider) with a menu entry. It may ask for
your password once, to turn on ntsync, which makes the apps much faster. Then open **Neutron
Collider** and install your apps from its Mud Hut tab.

`neutron update` updates everything and moves your prefixes to the new runtime.
`neutron uninstall` removes Neutron; it asks before deleting any prefix.

### The `neutron` CLI

`neutron` is the engine's front door — the same interface Collider drives. Add `--json` to any
command for structured output.

| Command | What it does |
| :--- | :--- |
| `neutron setup` / `update` / `uninstall` | Install, update or remove everything (see above). |
| `neutron launch <app> [file]` | Launch an app through the Neutron stack. Apps: `premiere`, `photoshop`, `lightroom`, `aftereffects`, `illustrator`, `animate`, `mediaencoder`, and `lightroomcc` (Lightroom, experimental). Supports `--prefix`, `--scale`, and opening a project file. |
| `neutron prefix provision <path>` | Make a Wine prefix Neutron-ready: Microsoft's components, the runtime's DXVK / vkd3d-proton / NVIDIA DLLs, fonts, display fixes. |
| `neutron prefix info <path>` | Report the paths and state Collider needs. |
| `neutron apps --prefix <path>` | List apps and install status in a prefix. |
| `neutron doctor --prefix <path>` | Health-check the prefix and stack. |
| `neutron teardown [--app <id>]` | Close one app, or the whole prefix, cleanly — apps save their preferences, and Adobe's orphaned daemons are swept so they can't wedge the next launch. |
| `neutron display` | Show the display scale Neutron will use, and whether it is one Adobe's UI lays out cleanly. |
| `neutron runtime install --version <v>` | Install a specific [neutron-wine](https://github.com/Nico-LaFoucate/neutron-wine) version (e.g. a pre-release), verified against its sha256. |

---

## Collider — the companion launcher

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/collider-neutron-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/collider-neutron-light.png">
  <img src="assets/collider-neutron-light.png" alt="Collider" width="120">
</picture>

</div>

Neutron is the engine; **Collider** is the cockpit. It's a graphical launcher and prefix manager
built to sit on top of Neutron — one tinted tile per installed app, installing apps through Mud
Hut, prefix provisioning, display scaling and theming, all without touching a terminal.

Collider lives in its [**own repository**](https://github.com/Nico-LaFoucate/Collider). Neutron is
fully usable on its own via the CLI above — Collider is the convenience layer for people who'd
rather click than type.

---

## Repository layout

| Path | Contents |
| :--- | :--- |
| [`bin/neutron`](bin/) | The Neutron CLI — the engine front door. |
| [`scripts/`](scripts/) | The CLI's release script and the support snapshot tool. |
| [`tests/`](tests/) | Tests for the CLI. |

Documentation, known issues and guides live on the wiki at
[neutronproject.org/wiki](https://neutronproject.org/wiki/).

---

## Reporting bugs

Report problems with launching and running the apps, and with the `neutron` CLI, on this
repository's [Issues](https://github.com/Nico-LaFoucate/Neutron/issues/new/choose). The form asks for
your `neutron --version` and `neutron doctor` output. Collider, Mud Hut and neutron-wine each have
their own Issues for problems with that piece. Questions go to
[Discussions](https://github.com/Nico-LaFoucate/Neutron/discussions). Report security problems
privately: see [`SECURITY.md`](SECURITY.md).

---

## Contributing

Contributions are welcome — please open an issue to discuss approach before large PRs. The ground
rules (full version in [`CONTRIBUTING.md`](CONTRIBUTING.md)):

- **Test on a real app.** Run the Adobe app your change affects, before and after.
- **Windows behavior is the reference.** When Neutron behaves differently from Windows, that is our
  bug, and the fix makes it behave like Windows.
- **No per-app hacks in Wine.** Fix what Wine gets wrong, so every app that depends on it benefits.
  Per-app launch and compatibility settings are fine.
- **Sign off your commits** (`git commit -s`, the Developer Certificate of Origin). There is no CLA.

AI-assisted contributions are welcome if you tested them on real apps and can explain them.
Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

---

## License

The `neutron` CLI is original code, licensed under the **GNU Lesser General Public License,
version 2.1 or later** (`LGPL-2.1-or-later`). See [`LICENSE`](LICENSE) for the full text. The
patches Neutron runs on live in [neutron-wine](https://github.com/Nico-LaFoucate/neutron-wine), where
each patch file carries the license of the project it modifies.

---

## Disclaimer

Neutron is an independent project by Nico LaFoucate and Ficus Media Group. Adobe and its product
names are trademarks of Adobe Inc. Neutron is not affiliated with or endorsed by Adobe.

Users must provide their own legally acquired Adobe licenses and accounts.

Neutron never modifies Adobe's program files. It changes one display setting in Adobe's own
preferences (`DS.DisableDirectXDisplay` in `Debug Database.txt`) and adds three compatibility flags
to aescripts panels' `manifest.xml` (the original is backed up).
