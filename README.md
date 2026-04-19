# Omarchy Extras

Extra setup on top of stock [Omarchy](https://omarchy.com). Run after a fresh install:

```bash
bash install.sh
```

The script is idempotent — safe to re-run. Model-specific fixes are gated by DMI detection.

**Supported models:**
- ASUS Zenbook 14 UX3405CA
- Samsung Galaxy Book6 Pro NP940XJG-KGDUK

## What the script does

### Common (all models)

- **Packages:** zed-bin, proton-pass-bin
- **Dev toolchains:** node, rust (via mise)
- **npm globals:** claude-code
- **Touchpad:** natural scroll, clickfinger, no tap-to-click
- **Nightlight:** auto warm screen at 20:00, daylight at 07:00
- **Lock screen shortcut:** Super + Shift + L
- **Battery:** PCI power management, NMI watchdog off, dirty writeback 15s, PCIe ASPM powersupersave, Bluetooth off by default, turbo boost auto-toggle via udev (on AC, off on battery)
- **Tailscale:** install, set operator, enable systray

### Zenbook 14 UX3405CA only

- NVMe APST latency cap (`nvme_core.default_ps_max_latency_us=5500`) — works around Micron 2500 I/O timeouts

### Galaxy Book6 Pro NP940XJG-KGDUK only

- **Panel Replay black screen fix:** disables `xe.enable_panel_replay=0` kernel
  param — Panel Replay (PSR successor) on the Panther Lake / Arc B390 xe driver
  causes intermittent black screen.
- **Caps Lock keyboard fix:** Omarchy's default `kb_options =
  compose:caps` breaks Caps Lock on this model; the script clears it.
- **Camera enablement** (Samsung SC200PC sensor on Intel IPU7) is
  delegated to a separate repo,
  [**sc200pc-linux**](https://github.com/jabbslad/sc200pc-linux). The
  install script clones it under `~/dev/sc200pc-linux` and runs its
  installer. On this laptop the installer builds two DKMS kernel
  modules (the SC200PC sensor driver and an IPU-bridge override that
  adds the `SSLC2000` ACPI HID), ships a small libcamera tuning YAML,
  and a WirePlumber rule that hides the raw IPU7 ISYS V4L2 nodes.
  **Stock Arch `libcamera` is used unmodified — no libcamera patches.**
  Camera works for Chromium / qcam / PipeWire-fed apps via libcamera's
  "simple" pipeline handler with software ISP. Image quality is
  functional but not yet production — see the sc200pc-linux README.
- An in-depth investigation of the proprietary Intel IPU7 vendor HAL
  path was archived to
  [**sc200pc-ipu7-hal-exploration**](https://github.com/jabbslad/sc200pc-ipu7-hal-exploration).
  The HAL path is unworkable on this sensor without Intel-internal
  tooling; the libcamera + soft-ISP path is the same one mainline
  libcamera + Fedora / Ubuntu use for IPU6/IPU7 webcams in 2026.

## Pre-install: Galaxy Book6 Pro black screen fix

The Panther Lake / Arc B390 xe driver's Panel Replay feature can cause a black
screen during the Omarchy installer. At the Limine boot menu:

1. Select the boot entry
2. Press **E** to edit the kernel command line
3. Append `xe.enable_panel_replay=0`
4. Boot

This is a one-shot edit — repeat it for the first boot after install until you
run `install.sh`, which makes it permanent via a limine drop-in.

## Manual steps after install

### Chromium Memory Saver

The single biggest power win. Without this, background tabs can consume 14%+ CPU continuously.

Settings → Performance → enable **Memory Saver**

### Temporary battery tweaks

These reset on reboot. Apply as needed:

**Lower screen brightness** (~60%):
```bash
brightnessctl set 60%
```

**Re-enable Bluetooth** (disabled by default, re-enable when needed):
```bash
rfkill unblock bluetooth
```

**Disable Turbo Boost** (caps CPU at base clock):
```bash
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
```

### Monitoring

```bash
upower -i "$(upower -e | grep BAT)" | grep energy-rate
```

Zenbook tuning notes: https://gist.github.com/jabbslad/e65ad403f5c3ebe3ca739d9e228245a0
