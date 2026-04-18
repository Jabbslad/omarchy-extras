# intel-ipu7-camera-sc200pc

Patchable local replacement package for `intel-ipu7-camera` on the
Galaxy Book6 Pro SC200PC bring-up machine.

This package exists for one reason: to move HAL experiments out of the
installed `/usr` tree and into a reproducible package directory where
future `libcamhal` / `icamerasrc` patches can be carried intentionally.

It is not the default recommended camera path. The current practical path
is still:

- [`sc200pc-dkms`](../sc200pc-dkms)
- [`sc200pc-libcamera-pipewire`](../sc200pc-libcamera-pipewire)

Use this package only when debugging the vendor HAL.

## Scope

This package rebuilds the userspace part of the Intel camera stack from
the same pinned upstream sources used by the Omarchy wrapper repo:

- `ipu7-camera-bins`
- `ipu7-camera-hal`
- `icamerasrc`

It also installs the service/config layer needed for the current
SC200PC-focused HAL experiment:

- `camera-init.service`
- `v4l2-relayd@ipu7` drop-in
- PipeWire / WirePlumber rules
- udev rules
- sleep hook

It intentionally `provides` and `conflicts` with `intel-ipu7-camera`.

## Pinned upstream commits

Current pins are taken from
`TsaiGaggery/hurrican_omarchy_enabling:mipi-camera-ptl/build-from-source/mipi_install_omarchy_6196.sh`:

- `ipu7-camera-bins`: `403c67db6b279dd02752f11db6a34552f31a3ac5`
- `ipu7-camera-hal`: `b1f6ebef12111fb5da0133b144d69dd9b001836c`
- `icamerasrc`: `4fb31db76b618aae72184c59314b839dedb42689`

## Local patch workflow

Drop patches into:

- `local-patches/ipu7-camera-hal/`
- `local-patches/icamerasrc/`

The `PKGBUILD` applies every `*.patch` in those directories during
`prepare()`.

This is the intended place for future HAL experiments such as:

- `PipeManager::isSameStreamConfig()` workarounds
- `GraphConfig` / `CameraDevice` instrumentation
- `icamerasrc` startup behavior changes

Current local HAL patch stack now includes:

- input-edge Bayer / geometry waiver for SC200PC
- graph outer-node / output-node handling fixes
- scheduler profile additions for graph `100005`
- a minimal SW output stage so the IMX471 graph's `res=5` output node is
  no longer dropped before output binding

## Current technical blocker

Rebuilding the HAL is realistic, and the graph mismatch is no longer the
first stop point, but the HAL path is still not streaming end to end.

What now works:

- the patched HAL gets past the earlier `GraphConfig`, `PipeManager`,
  scheduler, and output-binding failures
- `gst-launch-1.0 -v icamerasrc device-name=sc200pc-uf ...` now powers
  the sensor on
- GStreamer negotiates live caps successfully:
  `NV12 1920x1080 @ 30 fps`

What still fails:

- `PipeLine: @findStageProducer: invalid stage input`
- `SensorHwCtrl: failed to get llp`
- `SensorManager: Failed to get frame Durations`
- `AiqEngine: Get sensor info failed`
- `AiqUnit: run 3A failed`
- `PSysDevice: Failed to add task No data available`
- repeated video-node poll timeouts after startup

Reasonable current reading of that failure chain:

- the old graph/input-edge mismatch forced a HAL patch, and that patch
  work was enough to reach real sensor startup
- the next blocker is later in the pipeline and likely involves sensor
  timing metadata expected by 3A, stage-producer wiring for the patched
  SW output path, or both

## Next planned work

This is the current plan to document, not a claim that the fix is known:

- inspect which V4L2 control the HAL is using when it says `failed to
  get llp`
- trace `PipeLine::findStageProducer()` on the active SC200PC path to
  see why one stage input is still unresolved
- capture a new focused HAL `LOG3` trace from this later state and use
  that to decide whether the next patch belongs in sensor-control
  handling, pipeline producer discovery, or PSYS task submission

## Build note

This package is meant for this local machine and has not been validated
in a clean chroot. The `PKGBUILD` stages Intel's proprietary headers and
libraries under a temporary sysroot before building `libcamhal` and
`icamerasrc`, and that path has now been validated with a full local
`makepkg -e --nodeps` run on the target machine.

Expected companion packages:

- `sc200pc-dkms`
- `sc200pc-ipu75xa-config`

## Build

```bash
cd packaging/intel-ipu7-camera-sc200pc
makepkg -Cfi
```
