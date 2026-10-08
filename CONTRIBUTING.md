# Contributing to Neutron

Neutron is four repositories, and this guide covers all of them:

| Repository | What it is | License |
| :--- | :--- | :--- |
| [Neutron](https://github.com/Nico-LaFoucate/Neutron) | The `neutron` CLI: setup, prefixes, launching apps | LGPL-2.1-or-later |
| [neutron-wine](https://github.com/Nico-LaFoucate/neutron-wine) | The patched Wine runtime, with its DXVK, vkd3d-proton and NVIDIA wrapper builds | LGPL-2.1-or-later |
| [Collider](https://github.com/Nico-LaFoucate/Collider) | The desktop app | Apache-2.0 |
| [Mud Hut](https://github.com/Nico-LaFoucate/Mud-Hut) | The installer | Apache-2.0 |

## Bugs, questions and security

- **Bugs** go to the Issues of the repository they belong to. An Adobe app that won't launch or
  misbehaves while running, and the `neutron` CLI, go to
  [Neutron's Issues](https://github.com/Nico-LaFoucate/Neutron/issues/new/choose). Collider, Mud Hut
  (installing an app) and neutron-wine each have their own. Each form asks for what we need.
- **Questions** go to [Discussions](https://github.com/Nico-LaFoucate/Neutron/discussions).
- **Security problems** are reported privately. See [SECURITY.md](SECURITY.md).
- `contact@neutronproject.org` is for press and business only. It is not a support channel.

## Before you start

Please open an issue to discuss the approach before a large pull request.

## Ground rules

- **Test on a real app.** Run the Adobe app your change affects and do the thing it changes,
  before and after. Unit tests and small test programs are welcome on top of that, not instead of
  it. Say in the pull request which app and version you tested, and what you did.
- **Windows behavior is the reference.** The goal is for each app to behave the way it does on
  Windows. When Neutron behaves differently, that is our bug, and the fix makes it behave like
  Windows. If you aren't sure how Windows behaves, say so.
- **No per-app hacks in Wine.** Fix what Wine gets wrong, so every app that depends on it benefits.
  Per-app launch settings (an environment variable or setting in an app's launch profile) are fine.
  Per-app code paths in Wine, and changes to Adobe's program files, are not.
- **Never commit** a Wine prefix, build output, or any file from Adobe.

## AI-assisted contributions

AI-assisted contributions are welcome when:

- you tested the change on real apps, the same as any other change; and
- you can explain what the change does and why it is right, in your own words.

You are responsible for what you submit, however it was written.

## Sign your commits (DCO)

Neutron uses the [Developer Certificate of Origin](https://developercertificate.org/) (DCO).
There is no CLA. Sign off every commit:

```sh
git commit -s
```

This adds a `Signed-off-by: Your Name <you@example.com>` line, which certifies that you wrote the
change or otherwise have the right to submit it under the repository's license. Forgot?
`git commit --amend -s` fixes the last commit, and `git rebase --signoff main` fixes every commit
on your branch.

Your contribution is licensed under the license of the repository you contribute to (see the table
above). A patch to an upstream project (Wine, DXVK, vkd3d-proton and so on) carries that project's
license.

## Where changes go

- How a Windows API behaves under Wine: neutron-wine, `patches/`.
- DXVK, vkd3d-proton and the NVIDIA wrappers: neutron-wine, `external/`.
- Prefixes, launching apps, app profiles, and setup, update and uninstall: the `neutron` CLI
  (`bin/neutron` in this repository).
- The desktop app: Collider. Collider is a front end for CLI commands, so behavior belongs in the
  CLI and Collider calls it.
- Installing Adobe apps: Mud Hut.

## Building and testing

- **Neutron:** the CLI is one Python file, `bin/neutron`. Run it with `python3 bin/neutron`, and the
  tests with `python3 -m unittest discover tests`.
- **neutron-wine:** see the Build section of its [README](https://github.com/Nico-LaFoucate/neutron-wine#build).
- **Collider:** `npm ci`, then `npm run tauri dev`. You need Rust, Node.js and Tauri's Linux
  system dependencies.
- **Mud Hut:** `cargo build` and `cargo test`.

## Pull requests

- One change per pull request.
- Say what you tested: the app and its version, your distribution, desktop and GPU, and what you
  saw before and after the change.
- For anything visual, include a screenshot.

## Code of conduct

Everyone taking part in Neutron follows the [code of conduct](CODE_OF_CONDUCT.md).
