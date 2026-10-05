# Contributing to Neutron

Neutron is an experimental-alpha compatibility layer for Adobe creative apps on Linux. Contributions
are welcome — please open an issue to discuss approach before large PRs.

## Ground rules learned the hard way
- **Verify before patching.** Adobe binaries are stripped; route around by instrumenting OUR side
  (Wine/DXVK/vkd3d), not by guessing Adobe's logic.
- **Patch discipline:** exact anchors, abort on mismatch, back up, verify the marker is in the
  deployed DLL after build (`strings <dll> | grep <marker>`), confirm a clean build.
- **Prefer correct fixes over workarounds.** The program-monitor fix is a single supported Premiere
  preference, not a pile of blits — that's the bar.
- **Test each change against a real Premiere session** (cold-start display, playback, export).
- **Never commit a Wine prefix or build artifacts** (see `.gitignore`).

## Where things are
- `bin/neutron` — the CLI.
- `scripts/` — the ucrtbase shim the CLI builds, and the support snapshot tool.
- `tests/` — tests for the CLI.
- The engine's fixes live in the neutron-wine repository.
