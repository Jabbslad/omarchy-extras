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

- **Kernel path works end-to-end.** `v4l2-ctl --stream-mmap` on
  `/dev/video0` captures real 4 247 552-byte Bayer BGGR raw10 frames
  (1928×1088 @ 30 fps). Three packages supply this:
  - `packaging/ipu-bridge-sslc2000/` — DKMS module replacing the
    in-tree `ipu-bridge.ko` with one that recognises ACPI HID
    `SSLC2000`
  - `packaging/sc200pc-dkms/` — DKMS sc200pc V4L2 sensor driver; its
    141-entry init table was reverse-engineered from the OEM Windows
    `sc200pc.sys` binary. Now exposes proper V4L2 timing controls
    (HBLANK, VBLANK, pixel_rate, digital_gain) required by the vendor
    HAL's 3A and PSYS pipeline
  - `packaging/sc200pc-ipu75xa-config/` — vendor HAL assets / config
    for HAL experiments
- **Native libcamera path is the only working browser path today.**
  `cam`, `qcam`, `pipewire-libcamera`, and Chromium can all see the
  camera through the native path. Stock libcamera has no `CameraSensorHelper`
  for `sc200pc`, so AGC treats the raw V4L2 gain code as a linear gain
  multiplier and converges at effectively 1.0×; the symptom is dark,
  green-tinted frames. `packaging/sc200pc-libcamera-pipewire/` now ships
  a udev override for `Intel IPU7 ISYS Capture *` so the native path can
  access `/dev/video0` even though `intel-ipu7-camera` hides it by
  default for the vendor HAL workflow, and it also ships
  `rebuild-libcamera-with-sc200pc-support`, which applies
  [patches/libcamera-sc200pc.patch](/home/jabbslad/dev/omarchy-extras/patches/libcamera-sc200pc.patch)
  to the Arch `libcamera` PKGBUILD (adds `CameraSensorHelperSc200pc`
  with `gain = code / 16`, black level 64-at-10-bit, and a matching
  `CameraSensorProperties` entry) and reinstalls. After that, AGC
  converges and the browser path works, but image quality is still
  clearly unfinished: indoor scenes are low-saturation with an olive /
  monochrome cast, exposure tuning is still hand-tuned, and the simple
  IPA YAML remains a first-pass approximation rather than measured
  calibration. Treat the native path as functional but not production
  quality yet.
- **Vendor HAL path is blocked on Intel tooling.**
  [packaging/sc200pc-ipu75xa-config/](/home/jabbslad/dev/omarchy-extras/packaging/sc200pc-ipu75xa-config)
  carries the Windows-derived AIQB / graph assets, and
  [packaging/intel-ipu7-camera-sc200pc/](/home/jabbslad/dev/omarchy-extras/packaging/intel-ipu7-camera-sc200pc)
  carries patches (0001–0005) that fix pipeline construction. As of
  April 18, 2026, the patched HAL successfully loads the Windows graph
  binary, runs 3A, and constructs the PSYS pipeline. The blocker is a
  per-graph hash mismatch: the Windows graph binary's autogen data
  layout (hash `0xE7F37F28`) is incompatible with the Linux HAL's
  compiled layout (hash `0x246C440B`). The IMX471 graph has a matching
  1920×1080 resolution but its topology format descriptors also differ.
  Resolving this requires Intel to generate a Linux-native graph binary
  using their proprietary graphspec compiler. A response to
  [intel/ipu7-drivers#62](https://github.com/user/intel/ipu7-drivers/issues/62)
  with our driver and findings would be valuable to move this forward.
- Apps that read raw V4L2 directly (opencv, custom gstreamer pipelines
  with `videoconvert`/`bayer2rgb`) can use `/dev/video0` today. Native
  `libcamera` consumers can also be used for diagnostics, but should not
  be expected to produce good image quality yet.
- `install.sh` does not yet pull these packages in automatically;
  install them manually on the target machine while the stack is being
  stabilized
- see:
  - [camera-issue-report.md](/home/jabbslad/dev/omarchy-extras/camera-issue-report.md)
  - [camera-bringup-plan.md](/home/jabbslad/dev/omarchy-extras/camera-bringup-plan.md)
  - [patches/ipu-bridge-add-sslc2000.patch](/home/jabbslad/dev/omarchy-extras/patches/ipu-bridge-add-sslc2000.patch)
  - [packaging/ipu-bridge-sslc2000/](/home/jabbslad/dev/omarchy-extras/packaging/ipu-bridge-sslc2000)
  - [packaging/sc200pc-dkms/](/home/jabbslad/dev/omarchy-extras/packaging/sc200pc-dkms)
  - [packaging/sc200pc-ipu75xa-config/](/home/jabbslad/dev/omarchy-extras/packaging/sc200pc-ipu75xa-config)
  - [packaging/sc200pc-libcamera-pipewire/](/home/jabbslad/dev/omarchy-extras/packaging/sc200pc-libcamera-pipewire)

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
