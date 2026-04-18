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
| `/etc/camera/ipu75xa/gcss/SC200PC_KAFC917.IPU75XA.bin` | Windows driver `graph_settings_SC200PC_KAFC917_PTL.bin` (renamed) | Reference SC200PC graph blob, not the current default runtime graph |
| `/etc/camera/ipu75xa/sensors/sc200pc-uf.json` | This package | Sensor HAL descriptor |
| `/usr/bin/sc200pc-hal-check` | This package | HAL diagnostic helper |
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
- the HAL path is still blocked, but the failure is now narrowed down:
  libcamhal loads `sc200pc-uf.json`, the AIQB, and the sensor driver,
  but the only Linux-readable graph blob we have (`IMX471_BBG803N3`)
  expects the wrong raw input geometry / Bayer order for SC200PC
- with the patched HAL package
  [`intel-ipu7-camera-sc200pc`](../intel-ipu7-camera-sc200pc), that
  graph mismatch is no longer the immediate stop point: the sensor LED
  comes on, `icamerasrc` negotiates
  `video/x-raw(memory:DMABuf), format=NV12, width=1920, height=1080, framerate=30/1`,
  and the stream reaches live startup before failing later

This package therefore carries a promising vendor asset set, but not a
working desktop stack.

## Why the HAL path is blocked

This is the current source-backed diagnosis, not a guess:

- the sensor driver now probes cleanly and the HAL startup control path
  works; the earlier probe-time V4L2 control failures were fixed in
  [`sc200pc-dkms`](../sc200pc-dkms)
- the Linux HAL loads `SC200PC_KAFC917_PTL.aiqb` successfully
- the Windows-extracted `SC200PC_KAFC917.IPU75XA.bin` fails even
  earlier in the Linux HAL graph reader, so it is not a drop-in Linux
  graph blob
- the fallback Linux-readable graph,
  `IMX471_BBG803N3.IPU75XA.bin`, does load, but HAL debug traces show
  it creates a PSYS input edge for `stream 60001` at
  `2328x1748 BA10/GRBG10`
- SC200PC only exposes `1928x1088 SBGGR10/BGGR10` through ISYS, so
  `PipeManager` rejects the bind before pipeline creation
- Intel's HAL has exactly one Bayer compatibility workaround there:
  internal `GRBG10` may bind to external `RGGB10`; there is no
  equivalent workaround for `BGGR10`, and no workaround for the
  `2328x1748` vs `1928x1088` size mismatch

The practical consequence is that there is no plausible JSON-only fix
left. The remaining options are:

- obtain a Linux-compatible SC200PC IPU75XA graph blob
- patch and rebuild Intel's HAL
- or keep using the working native `libcamera` path

## Latest patched-HAL result

Latest observed state with the patched
[`intel-ipu7-camera-sc200pc`](../intel-ipu7-camera-sc200pc) package:

- the earlier `GraphConfig`, `bindExternalPorts`, scheduler, and
  output-node bring-up failures were bypassed by local HAL patches
- the camera LED now turns on during `gst-launch-1.0`
- GStreamer negotiates live caps successfully:
  `video/x-raw(memory:DMABuf), format=NV12, width=1920, height=1080, framerate=30/1`
- but frame delivery still does not start

Current error chain from that state:

- `PipeLine: @findStageProducer: invalid stage input`
- `V4l2_device_cc: GetControl ... VIDIOC_G_EXT_CTRLS ... Invalid argument`
- `SensorHwCtrl: failed to get llp.`
- `SensorManager: Failed to get frame Durations ret:-1`
- `AiqEngine: Get sensor info failed:-1`
- `AiqUnit: run 3A failed.`
- `PSysDevice: Failed to add task No data available`
- repeated `Poll: Device node fd 14 poll timeout`

Inference from those logs:

- the stream is no longer dying during graph parsing or caps negotiation
- HAL now appears to be blocked on a later-stage combination of:
  sensor timing metadata expected by 3A, producer wiring for the staged
  PSYS pipeline, or both

## Next investigation plan

This is the documented next plan only. It has not been attempted here.

- inspect the exact control path behind `failed to get llp` to see which
  sensor timing query the HAL expects from `/dev/v4l-subdev4`
- trace `PipeLine::findStageProducer()` against the patched SW output
  stage path to see which stage input is still considered invalid
- capture a focused `LOG3` trace from this newer state and follow
  `SensorHwCtrl`, `SensorManager`, `AiqEngine`, `PipeLine`, and
  `PSysDevice` together instead of only graph-setup tags
- only after that decide whether the next blocker is primarily a missing
  sensor control / timing value, a stage-producer routing bug, or a
  PSYS submission contract mismatch

## Current graph strategy

The active runtime graph is selected by `graphSettingsFile` inside
`sc200pc-uf.json`.

Current default:

- `graphSettingsFile`: `IMX471_BBG803N3.IPU75XA.bin`
- SC200PC JSON + SC200PC AIQB + IMX471 Linux-compatible graph

Why:

- the Windows-extracted `SC200PC_KAFC917.IPU75XA.bin` appears to be in a
  different container format than the Linux IPU75XA HAL expects
- the IMX471 graph is already known to load in the Linux HAL, so it was
  the least-bad Linux-compatible baseline for experimentation
- however, it is now known to expect an internal raw input of
  `2328x1748 GRBG10`, not SC200PC's native `1928x1088 BGGR10`

This means the packaged SC200PC graph blob is currently kept for
reference and investigation, not as the default runtime graph.

## Trying the HAL path anyway

Install the package, then:

```bash
sudo systemctl enable --now v4l2-relayd@ipu7
systemctl --user restart wireplumber pipewire
```

At the time of writing this no longer fails at the earliest graph-setup
stage if the patched `intel-ipu7-camera-sc200pc` package is installed,
but it still does not produce frames and is not expected to yield a
working Chromium stream yet.

Before changing any graph-related setting, inspect the current runtime
state with:

```bash
sc200pc-hal-check
```

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
layout at the media-controller / ISYS level. Applied changes:

- `name` / `description` / MediaCtl entity names → `sc200pc`
- Bayer order: `SRGGB10` → `SBGGR10`
- `sensor.info.colorFilterArrangement`: `0` (RGGB) → `3` (BGGR)
- `supportedTuningConfig`: `IMX471_BBG803N3_PTL` → `SC200PC_KAFC917_PTL`
- ISys raw format: `V4L2_PIX_FMT_SRGGB10` → `V4L2_PIX_FMT_SBGGR10`

The graph field deserves a separate note:

- the package keeps `SC200PC_KAFC917.IPU75XA.bin` for reference
- the active default remains `IMX471_BBG803N3.IPU75XA.bin` because the
  SC200PC Windows blob is not readable by the Linux graph loader
- even that IMX471 graph is still incompatible with SC200PC at the PSYS
  input edge, so the current default is an investigation baseline, not a
  working configuration

## Verification after install

```bash
ls /etc/camera/ipu75xa/SC200PC_KAFC917_PTL.aiqb
ls /etc/camera/ipu75xa/gcss/SC200PC_KAFC917.IPU75XA.bin
ls /etc/camera/ipu75xa/sensors/sc200pc-uf.json
grep sc200pc /etc/camera/ipu75xa/libcamhal_configs.json
systemctl status v4l2-relayd@ipu7
wpctl status
sc200pc-hal-check
```
