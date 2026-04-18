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

- **Caps Lock keyboard fix:** Omarchy's default `kb_options =
  compose:caps` breaks Caps Lock on this model; the script clears it.
- **Camera enablement** (Samsung SC200PC sensor on Intel IPU7) is
  delegated to a separate repo,
  [**sc200pc-linux**](https://github.com/jabbslad/sc200pc-linux). The
  install script clones it under `~/dev/sc200pc-linux` and runs its
  installer, which builds the kernel modules (DKMS), patches and
  rebuilds Arch `libcamera` with the SC200PC sensor helper, and wires
  up PipeWire. Camera works for Chromium / qcam / PipeWire-fed apps via
  libcamera's "simple" pipeline handler with software ISP. Image
  quality is functional but not yet production — see the sc200pc-linux
  README.
- An in-depth investigation of the proprietary Intel IPU7 vendor HAL
  path was archived to
  [**sc200pc-ipu7-hal-exploration**](https://github.com/jabbslad/sc200pc-ipu7-hal-exploration).
  The HAL path is unworkable on this sensor without Intel-internal
  tooling; the libcamera + soft-ISP path is the same one mainline
  libcamera + Fedora / Ubuntu use for IPU6/IPU7 webcams in 2026.

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
