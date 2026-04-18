# sc200pc-ipu75xa-config

Experimental vendor HAL asset package for the Samsung/SmartSens SC200PC
front camera (module `KAFC917`) on the Galaxy Book6 Pro.

This package is not the working default camera path. It exists for HAL
research only while the native `libcamera` path remains the only browser
/ desktop path that actually streams.

Requires `intel-ipu7-camera` for the IPU7 HAL libraries and directory
layout. Stacks with:

- [`ipu-bridge-sslc2000`](../ipu-bridge-sslc2000) — patched ipu-bridge
  module that recognises ACPI HID `SSLC2000`
- [`sc200pc-dkms`](../sc200pc-dkms) — V4L2 sensor driver for SC200PC
  (streams 1928×1088 raw10 BGGR @ 30 fps over 2-lane MIPI)

## Files installed

| Path | Source | Purpose |
|------|--------|---------|
| `/etc/camera/ipu75xa/SC200PC_KAFC917_PTL.aiqb` | Windows driver `SC200PC_KAFC917_PTL.aiqb` | AIQ tuning profile |
| `/etc/camera/ipu75xa/gcss/SC200PC_KAFC917.IPU75XA.bin` | Windows driver `graph_settings_SC200PC_KAFC917_PTL.bin` (renamed) | IPU7 graph settings |
| `/etc/camera/ipu75xa/sensors/sc200pc-uf.json` | This package | Sensor HAL descriptor |
Post-install scriptlet also adds `"sc200pc-uf-0"` to the
`availableSensors` array inside
`/etc/camera/ipu75xa/libcamhal_configs.json` (owned by
`intel-ipu7-camera`); removed on uninstall.

The relay files themselves are still expected to come from
`intel-ipu7-camera`:

- `/etc/v4l2-relayd.d/ipu7.conf`
- `/etc/systemd/system/v4l2-relayd@ipu7.service.d/override.conf`

## Current status

What is known today:

- kernel capture works through `ipu-bridge-sslc2000` + `sc200pc-dkms`
- the native `libcamera` path is mechanically working, including
  PipeWire, qcam, and Chromium camera streaming
- but native image quality is still poor because the simple IPA path
  lacks a real `CameraSensorHelper` and vendor-quality tuning for
  `sc200pc`
- the HAL path is still blocked: libcamhal loads `sc200pc-uf.json` and
  the AIQB, but fails in `GraphConfig` / `PipeManager` and does not
  produce a working browser stream

This package therefore carries a promising vendor asset set, but not a
working desktop stack.

## Trying the HAL path anyway

Install the package, then:

```bash
sudo systemctl enable --now v4l2-relayd@ipu7
systemctl --user restart wireplumber pipewire
```

At the time of writing this still fails during HAL graph setup and is
not expected to yield a working Chromium stream.

## Asset origin

The `.aiqb` and `.IPU75XA.bin` blobs are extracted from the Windows
OEM driver package (Microsoft Update Catalog, hardware ID
`ACPI\SSLC2000`, version `71.26100.0.11`, GUID
`aa876ff4-ff3e-4690-849b-6839f5791817`). They are proprietary Intel /
Samsung camera tuning; they are shipped here for personal use on the
Galaxy Book6 Pro. For public redistribution, the same licence questions
apply as to the OEM binaries already bundled by `intel-ipu7-camera`
(IMX471 / OV08X40 / OV13B10).

## `sc200pc-uf.json` derivation

Template: `imx471-uf.json` from `intel-ipu7-camera` (Apache-2.0,
Copyright Intel 2022). Both sensors share the 1928×1088 raw10 output
layout. Applied changes:

- `name` / `description` / MediaCtl entity names → `sc200pc`
- Bayer order: `SRGGB10` → `SBGGR10`
- `sensor.info.colorFilterArrangement`: `0` (RGGB) → `3` (BGGR)
- `supportedTuningConfig`: `IMX471_BBG803N3_PTL` → `SC200PC_KAFC917_PTL`
- `graphSettingsFile`: `IMX471_BBG803N3.IPU75XA.bin` → `SC200PC_KAFC917.IPU75XA.bin`
- ISys raw format: `V4L2_PIX_FMT_SRGGB10` → `V4L2_PIX_FMT_SBGGR10`

## Verification after install

```bash
ls /etc/camera/ipu75xa/SC200PC_KAFC917_PTL.aiqb
ls /etc/camera/ipu75xa/gcss/SC200PC_KAFC917.IPU75XA.bin
ls /etc/camera/ipu75xa/sensors/sc200pc-uf.json
grep sc200pc /etc/camera/ipu75xa/libcamhal_configs.json
systemctl status v4l2-relayd@ipu7
wpctl status
```
