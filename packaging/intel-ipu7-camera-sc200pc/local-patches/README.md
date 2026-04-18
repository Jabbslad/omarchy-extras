Place local patch series here.

Supported patch roots:

- `local-patches/ipu7-camera-hal/*.patch`
- `local-patches/icamerasrc/*.patch`

The `PKGBUILD` applies them in lexical order during `prepare()`.

Suggested first targets for SC200PC HAL experiments:

- `ipu7-camera-hal/src/core/processingUnit/PipeManager.cpp`
- `ipu7-camera-hal/src/platformdata/gc/GraphConfig.cpp`
- `ipu7-camera-hal/src/core/CameraDevice.cpp`

Keep patches small and hypothesis-driven. The current blocker is a real
graph/input mismatch, not just missing registration or control support.
