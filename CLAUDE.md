# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Personal post-install layer on top of stock [Omarchy](https://omarchy.com) (Arch + Hyprland) for two specific laptops:

- ASUS Zenbook 14 UX3405CA
- Samsung Galaxy Book6 Pro NP940XJG-KGDUK

What lives here:

- `install.sh` — idempotent shell script that tweaks an installed Omarchy system (packages, battery/power tuning, touchpad, Hyprland config, nightlight, Tailscale). On Galaxy Book6 Pro it also clones [sc200pc-linux](https://github.com/jabbslad/sc200pc-linux) and runs its camera installer.

Camera enablement (DKMS kernel modules, libcamera helper / IPA, install script) lives in its own repo: **[sc200pc-linux](https://github.com/jabbslad/sc200pc-linux)**. The proprietary IPU7 vendor HAL investigation is archived in **[sc200pc-ipu7-hal-exploration](https://github.com/jabbslad/sc200pc-ipu7-hal-exploration)** — that path is unworkable on this sensor without Intel-internal tooling; the libcamera + software-ISP path in sc200pc-linux is the same architecture mainline libcamera + Fedora / Ubuntu use for IPU6/IPU7 webcams in 2026.

## install.sh architecture

- One file, top-to-bottom, `set -euo pipefail`. Idempotency is the contract: every section must be safe to re-run.
- Model gating is done with `is_zenbook_ux3405ca` / `is_galaxybook6_pro` shell functions that match against `/sys/class/dmi/id/product_*`. Anything model-specific must be guarded.
- Persistent kernel cmdline changes go through limine drop-ins under `/etc/limine-entry-tool.d/` followed by `sudo limine-update` — do not edit limine config directly. The script also applies these changes immediately to `/sys/...` so a reboot isn't required.
- udev rules live under `/etc/udev/rules.d/` with `50-`/`72-` prefixes; sysctls under `/etc/sysctl.d/50-*.conf`. Reuse those prefixes.
- Hyprland config edits target the user's `~/.config/hypr/*.conf` files in place via `sed`/`grep -q` guards rather than rewriting whole files — this preserves stock Omarchy's structure.
- When undoing a previous approach, leave a `sudo rm -f` line for the old artifact (see VMD / USB autosuspend cleanup) so re-running on an old install reverts cleanly.

## Camera enablement (Galaxy Book6 Pro)

Lives in **[sc200pc-linux](https://github.com/jabbslad/sc200pc-linux)** (working path) and **[sc200pc-ipu7-hal-exploration](https://github.com/jabbslad/sc200pc-ipu7-hal-exploration)** (archived investigation). The Galaxy Book6 block in `install.sh` clones the working repo under `~/dev/sc200pc-linux` and runs its `install.sh`. Don't reintroduce camera packages or patches here — they belong in those repos.
