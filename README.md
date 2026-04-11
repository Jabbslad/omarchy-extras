# Omarchy Extras — ASUS Zenbook 14 UX3405CA

Extra setup on top of stock [Omarchy](https://omarchy.com). Run after a fresh install:

```bash
bash install.sh
```

The script is idempotent — safe to re-run.

## What the script does

- **Packages:** zed-bin, proton-pass-bin, python-terminaltexteffects
- **Dev toolchains:** node, rust (via mise)
- **npm globals:** claude-code
- **Touchpad:** natural scroll, clickfinger, no tap-to-click
- **Nightlight:** auto warm screen at 20:00, daylight at 07:00
- **Lock screen shortcut:** Super + Shift + L
- **Battery:** PCI power management, NMI watchdog off, dirty writeback 15s, PCIe ASPM powersupersave, Bluetooth off by default
- **Tailscale:** install, set operator, enable systray

## Manual steps after install

### Chromium Memory Saver

The single biggest power win. Without this, background tabs can consume 14%+ CPU continuously.

Settings → Performance → enable **Memory Saver**

### Temporary battery tweaks

These reset on reboot. Apply as needed:

**Lower screen brightness** (~60%):
```bash
echo 240 | sudo tee /sys/class/backlight/intel_backlight/brightness
```

**Re-enable Bluetooth** (disabled by default, re-enable when needed):
```bash
rfkill unblock bluetooth
```

**Disable Turbo Boost** (caps CPU at base clock, ~2.0 GHz):
```bash
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
```

### Monitoring

```bash
upower -i /org/freedesktop/UPower/devices/battery_BAT0 | grep energy-rate
```

See the full tuning guide: https://gist.github.com/jabbslad/e65ad403f5c3ebe3ca739d9e228245a0
