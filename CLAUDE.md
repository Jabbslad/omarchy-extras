# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Personal post-install layer on top of stock [Omarchy](https://omarchy.com) (Arch + Hyprland) for two specific laptops:

- ASUS Zenbook 14 UX3405CA
- Samsung Galaxy Book6 Pro NP940XJG-KGDUK

Two distinct things live here:

1. `install.sh` — idempotent shell script that tweaks an installed Omarchy system (packages, battery/power tuning, touchpad, Hyprland config, nightlight, Tailscale).
2. `packaging/` + `patches/` — Arch packages and kernel/userspace patches to bring the Galaxy Book6 Pro front camera (Samsung SC200PC sensor, ACPI HID `SSLC2000`) up on Linux. This is an in-progress hardware-enablement effort, not yet wired into `install.sh`.

## install.sh architecture

- One file, top-to-bottom, `set -euo pipefail`. Idempotency is the contract: every section must be safe to re-run.
- Model gating is done with `is_zenbook_ux3405ca` / `is_galaxybook6_pro` shell functions that match against `/sys/class/dmi/id/product_*`. Anything model-specific must be guarded.
- Persistent kernel cmdline changes go through limine drop-ins under `/etc/limine-entry-tool.d/` followed by `sudo limine-update` — do not edit limine config directly. The script also applies these changes immediately to `/sys/...` so a reboot isn't required.
- udev rules live under `/etc/udev/rules.d/` with `50-`/`72-` prefixes; sysctls under `/etc/sysctl.d/50-*.conf`. Reuse those prefixes.
- Hyprland config edits target the user's `~/.config/hypr/*.conf` files in place via `sed`/`grep -q` guards rather than rewriting whole files — this preserves stock Omarchy's structure.
- When undoing a previous approach, leave a `sudo rm -f` line for the old artifact (see VMD / USB autosuspend cleanup) so re-running on an old install reverts cleanly.

## Camera enablement (Galaxy Book6 Pro)

The SC200PC sensor has no upstream Linux driver. The working stack here has three layers:

1. **Kernel — `packaging/ipu-bridge-sslc2000/`**: DKMS replacement for the in-tree `ipu-bridge.ko`, patched to recognize ACPI HID `SSLC2000`. The patch source is also in `patches/ipu-bridge-add-sslc2000.patch`.
2. **Kernel — `packaging/sc200pc-dkms/`**: Out-of-tree V4L2 sensor driver (`sc200pc.c`). Init register table was reverse-engineered from the OEM Windows `sc200pc.sys`. Together with (1) this produces working raw10 BGGR frames on `/dev/video0`.
3. **Userspace — `packaging/sc200pc-libcamera-pipewire/`**: Ships an IPA YAML for libcamera's simple soft IPA, a udev rule to restore user access to the `Intel IPU7 ISYS Capture` node, and a `rebuild-libcamera-with-sc200pc-support` script that patches and rebuilds the Arch `libcamera` package with `patches/libcamera-sc200pc.patch` (adds `CameraSensorHelperSc200pc` and a matching `CameraSensorProperties` entry — without these AGC cannot converge and frames are dark/green).

A fourth package, `packaging/sc200pc-ipu75xa-config/`, carries vendor HAL assets (AIQB / graph binaries, derived from Windows). The vendor HAL path is **not working** (fails in `GraphConfig` / `PipeManager`) — treat these files as research-only. The `install.sh` Galaxy Book6 block actively *removes* HAL-only WirePlumber overrides (`10-disable-libcamera.conf`, `60-hide-ipu7-v4l2.conf`) so the native libcamera path is preferred.

The two paths conflict on PipeWire/WirePlumber state. After touching either side, restart the user services:

```bash
systemctl --user restart wireplumber pipewire xdg-desktop-portal xdg-desktop-portal-hyprland
```

## Building / testing the packages

All four are standard Arch PKGBUILDs — `cd packaging/<name> && makepkg -si`. The DKMS packages install sources to `/usr/src/<name>-<ver>/` and build against the running kernel via DKMS (`AUTOINSTALL="yes"`).

Sensor-side smoke test on a Galaxy Book6 Pro:

```bash
sc200pc-libcamera-check               # full diagnostic from sc200pc-libcamera-pipewire
v4l2-ctl --stream-mmap --stream-count=1 -d /dev/video0   # raw frame
cam -l                                # libcamera enumeration; warns if helper/properties missing
```

If `cam -l` warns "Failed to create camera sensor helper for sc200pc" or "No static properties available for 'sc200pc'", run `rebuild-libcamera-with-sc200pc-support`.

## Patches

`patches/` holds the upstream-shaped patches that the DKMS / rebuild scripts consume:

- `ipu-bridge-add-sslc2000.patch` — kernel, adds the SSLC2000 sensor entry to `ipu-bridge`.
- `libcamera-sc200pc.patch` — libcamera, adds `CameraSensorHelperSc200pc` (`gain = code / 16`, black level 64-at-10-bit) and a `CameraSensorProperties` entry.
- `sc200pc-libcamera-enum.patch` — additional libcamera enumeration tweak.

Keep these patches small and intended for upstream — the rebuild script splices them into stock Arch PKGBUILDs by anchor-matching existing patch lines.

## Working notes / status docs

`camera-issue-report.md`, `camera-bringup-plan.md`, `sc200pc-arch-packaging-plan.md`, `sc200pc-kernel-patch-checklist.md`, and `sc200pc-driver-skeleton.c` are unstaged scratchpads tracking the camera investigation. Read them for context before changing the camera packages, but they are not part of the published artifact.
