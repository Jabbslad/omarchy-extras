# Samsung Galaxy Book6 Pro (NP940XJG-KGDUK): internal camera uses Samsung/Intel `SC200PC` via ACPI `SSLC2000`, no Linux support path yet

## Update — 2026-04-17 (kernel-level streaming works)

## Update — 2026-04-18 (native browser path works, quality still poor)

The native `libcamera` path is now functionally working end-to-end:

1. `sc200pc` now exposes the minimum V4L2 subdev requirements libcamera
   needs to enumerate the sensor:
   - frame-size / frame-interval enumeration
   - crop/default/bounds/native-size selection rectangles
   - mandatory controls for `VBLANK`, `HBLANK`, `EXPOSURE`,
     `ANALOGUE_GAIN`
2. The control handlers now write real sensor registers:
   - exposure → `0x3e00` / `0x3e01` / `0x3e02`
   - analogue gain → `0x3e09`
3. Browser integration works through the native path once the HAL-only
   WirePlumber overrides are removed and the IPU7 ISYS node is made
   accessible to the user session.

However, image quality is still not good:

- indoor scenes remain low-saturation with a strong olive / near-
  monochrome cast
- tuning is still hand-edited in `sc200pc.yaml`, not chart-calibrated
- the path is usable for "having a working camera", but not yet for
  claiming acceptable production image quality

The vendor HAL path remains blocked exactly as described below.

Everything described in the original report below is now resolved at
the kernel level. The internal camera captures frames end-to-end:

1. **Bridge-side graph:** `ipu-bridge.ko` patched to recognize ACPI HID
   `SSLC2000` — shipped as DKMS in
   [packaging/ipu-bridge-sslc2000/](packaging/ipu-bridge-sslc2000).
   `intel-ipu7` logs `Found supported sensor SSLC2000:00`, graph forms
   with the sensor entity linked `ENABLED,IMMUTABLE` to CSI2 0.

2. **Sensor driver:** `sc200pc` (DKMS 0.3.0 in
   [packaging/sc200pc-dkms/](packaging/sc200pc-dkms)) binds, exposes
   `V4L2_CID_LINK_FREQ` (195 MHz DDR) and `V4L2_CID_PIXEL_RATE`
   (78 Mpix/s), writes a 141-entry init table extracted from the
   Windows `sc200pc.sys` driver, and toggles stream enable on/off.

3. **Streaming verified:** `v4l2-ctl --stream-mmap --stream-count=1`
   on `/dev/video0` captures a real frame (4 247 552 bytes, 1928×1088
   packed raw10 BGGR). ISYS traces show `FRAME_SOF` + `PIN_DATA_READY`
   + `STREAM_CAPTURE_DONE` with real timestamps, clean flush/close.

### Windows driver extraction

Since the `sc200pc.sys` init sequence had no upstream-compatible
Linux sibling (SC202CS in Espressif esp-video-components is NOT
register-compatible — different PLL block), the real init table was
reverse-engineered from the Windows binary.

- Source: Microsoft Update Catalog, search
  https://www.catalog.update.microsoft.com/Search.aspx?q=SSLC2000
- Hardware ID: `ACPI\SSLC2000`
- Version: `71.26100.0.11`, updated 2025-11-16
- Package: 27.7 MB CAB, update GUID
  `aa876ff4-ff3e-4690-849b-6839f5791817`
- Extracted files (retained out-of-tree for license reasons):
  `sc200pc.sys`, `sc200pc.inf`, `SC200PC_KAFC917_PTL.aiqb`,
  `SC200PC_KAFC917_PTL.cpf`, `graph_settings_SC200PC_KAFC917_PTL.bin`,
  plus the bundled IPU7 firmware and ISP DLLs.

Init table layout in `sc200pc.sys .rdata`: 16-byte entries
`{u32 op=1, u32 addr, u32 value, u32 reserved}`, terminated by
`{u32 addr=0xffff}`. Main streaming table starts at `.rdata + 0x670`
(141 entries, 1928×1088 raw10 30 fps 2-lane).

### Still open (for actual usability)

**4. HAL pipeline — BLOCKED on graph binary format.**

`packaging/sc200pc-ipu75xa-config/` is implemented and installs
cleanly: `SC200PC_KAFC917_PTL.aiqb`, `sc200pc-uf.json` (derived
from `imx471-uf.json`, same 1928×1088 resolution), and a post-install
scriptlet that registers `"sc200pc-uf-0"` in
`libcamhal_configs.json`. `/etc/v4l2-relayd.d/ipu7.conf` has been
patched locally to set `device-name=sc200pc-uf`. PipeWire now
advertises a "Hardware ISP Camera" device via `/dev/video50`.

However, the icamerasrc gstreamer pipeline fails at graph config.
libcamhal gets through JSON parsing, CSI port resolution (port 0),
I2C bus resolution (2-0036), AIQB load, then dies at:

```
GraphConfig: failed to init graph reader
```

Root cause: the `graph_settings_SC200PC_KAFC917_PTL.bin` extracted
from the Windows CAB has magic `0x5C63B5E7`, but Linux libcamhal's
`.IPU75XA.bin` format has magic `0x4229ABEE`. Different container
formats — simple renaming doesn't help.

Using `IMX471_BBG803N3.IPU75XA.bin` (same 1928×1088 resolution) as
a stand-in gets further: scheduler then demands `graphId 100005`
(not in stock `pipe_scheduler_profiles.json`; a local clone entry
was added). Pipeline then fails deeper at:

```
GraphConfig: getPSysContextId: Can't find node, stream 60001,
    outerNode ctxId 3
```

The graph's PSYS DAG is IMX471-specific and references nodes that
don't apply to the SC200PC video mode the HAL is trying to set up.

Linux `.IPU75XA.bin` graph binaries are produced by Intel's
proprietary `graphspec` compiler from XML descriptions — not
publicly available. No SC200PC Linux graph binary is known to
exist.

**Paths forward (not yet pursued):**

1. Obtain the SC200PC graph binary from Samsung/Intel via an upstream
   contact (probably unrealistic for a consumer-OEM-locked module).
2. Migrate Omarchy's userspace camera path to `libcamera` instead of
   `libcamhal`. libcamera uses YAML pipeline descriptions rather than
   pre-compiled graph bins, sidestepping the compiler gap but
   requiring PipeWire reconfiguration.
3. Skip the HAL entirely; use raw V4L2 captures from `/dev/video0`
   in apps that handle Bayer themselves (limited to dev/test — no 3A /
   tuning / ISP).

**5. Sensor driver V4L2 controls — minor, tracked separately.**

libcamhal calls `SetControl` on the sc200pc subdev and gets `-EINVAL`
for each. The driver currently exposes read-only `V4L2_CID_LINK_FREQ`
and `V4L2_CID_PIXEL_RATE` only. Needed additions: exposure
(`0x3e00`–`0x3e02`), analog gain (`0x3e09`), H/V flip (`0x3221`),
test pattern. Errors are survivable (pipeline continues past them
to the graph config step, which is the real blocker) but should be
implemented regardless for proper operation.

The rest of this report is retained as a snapshot of the
pre-graph-fix state; it predates everything above.

## Platform

- Model: Samsung Galaxy Book6 Pro NP940XJG-KGDUK
- CPU: Intel Core Ultra 7 358H / Core Ultra X7 358H class platform
- Kernel: `6.19.10-arch1-1-ptl` (Arch Linux)
- IPU stack: `intel_ipu7_isys`, `intel_ipu7_psys` loaded; `v4l2-relayd` running; no `/dev/video*` nodes appear

## What is now confirmed

### Live ACPI enumeration

The running Linux system exposes:

- `/sys/bus/acpi/devices/SSLC2000:00/hid` → `SSLC2000`
- `/sys/bus/acpi/devices/SSLC2000:00/path` → `\_SB_.LNK0`
- `/sys/bus/acpi/devices/SSLC2000:00/status` → `15`

So the firmware is definitively advertising the enabled camera as ACPI device `SSLC2000` on `LNK0`.

### Live ACPI method probing

Using `acpi_call`:

- `\_SB.LNK0._DDN` returns `"KAFC917"`
- `\_SB.LNK0._CRS` returns an I2C resource pointing at `\_SB.PC00.I2C3`
- The first active I2C address in `_CRS` is `0x36`

This matches the previously extracted NVS values:

```
L0BS = 0x3
L0A0 = 0x36
L0A1 = 0x50
L0DI = 0x2
L0SM = 0xFF
L0H0..L0H8 -> "SSLC2000"
```

So the active camera path is:

- ACPI device: `SSLC2000`
- camera module ID: `KAFC917`
- I2C controller: `I2C3`
- sensor I2C address: `0x36`
- likely EEPROM address: `0x50`

### Windows driver package

The public Microsoft Update Catalog package for `ACPI\SSLC2000` version `71.26100.0.11` contains:

- Catalog search URL: `https://www.catalog.update.microsoft.com/Search.aspx?q=SSLC2000`
- Package identity used during inspection:
  - hardware ID: `ACPI\SSLC2000`
  - version: `71.26100.0.11`
  - payload type: CAB

I did not preserve the direct time-limited CAB download URL in the repo. The stable source reference is the Catalog search page above plus the package version and hardware ID.

- `sc200pc.inf`
- `sc200pc.sys`
- `SC200PC_KAFC917_PTL.aiqb`
- `SC200PC_KAFC917_PTL.cpf`
- `graph_settings_SC200PC_KAFC917_PTL.bin`

The INF explicitly describes itself as:

- `INF file for installing SC200PC camera sensor (ACPI\SSLC2000) driver`

This is the strongest evidence collected so far: Windows does not treat this as an OmniVision reference design. It uses a dedicated `SC200PC` sensor driver and `KAFC917`-specific tuning / graph assets.

## Firmware mechanics

ACPI SSDT (`ssdt2.dsl`) declares camera device `\_SB.LNK0` with dynamic identity:

- `_HID` and `_CID` call `HCID(0)`
- `HCID()` uses `L0SM`
- when `L0SM = 0xFF`, `HCID()` falls through to `GRID(0)`
- `GRID(0)` returns the 9-byte string in `L0H0..L0H8`
- on this machine that string is `"SSLC2000"`

`LNK0` also exposes more than a simple HID:

- `_CRS` builds I2C resource descriptors from `L0A*`, `L0BS`, `L0DI`
- `SSDB()` builds a 0x6c-byte sensor metadata blob from `L0DV`, `L0CV`, `L0CK`, `L0CL`, `L0PP`, `L0VR`, `L0FI`, `L0PC`, `L0LA`, etc.
- `_DSM()` exposes additional camera metadata and device tables

This matters because the Windows `sc200pc.sys` driver clearly consumes BIOS/DSM/GPIO/I2C metadata beyond just the ACPI HID.

## Current Linux status

- There is **no upstream Linux sensor driver** for `SC200PC`
- The local Omarchy `intel-ipu7-camera` package ships configs for `IMX471`, `OV08X40`, and `OV13B10`, not `SC200PC`
- The local kernel has support for `OV02C10` / `OV13B10`, but not `SC200PC`
- No `/dev/video*` nodes appear for the internal camera on this machine

So the internal camera is not blocked by a missing generic IPU7 userspace package alone. The missing Linux path is sensor-specific.

## Full ACPI NVS dump (MNVS OperationRegion, slot 0)

```
CL00 = 0x1    (camera present)
L0EN = 0x1    (enabled)
C0TP = 0x1    (type: front)
L0BS = 0x3    (bus: i2c-2)
L0A0 = 0x36   (sensor i2c address)
L0A1 = 0x50   (EEPROM i2c address)
L0DI = 0x2    (device index)
L0SM = 0xFF   (sensor model index — BIOS left this at 0xFF, causing GRID() fallback)
L0H0..L0H8   → "SSLC2000" (HID bytes)
```

LNK1–LNK5 all have `_STA=0` — they are unused decoys; LNK0 is the only enabled camera.

## Power / control observations

`INT3472:00` (discrete PMIC driver) declares only a single regulator:

```
regulator.2: INT3472:00-avdd  [disabled, 0 users]
```

However, the Windows `sc200pc.sys` driver contains strings and logic for:

- GPIO handling (`gp_core_0%d`, `Reset`, `Power0`, `Power1`)
- I2C discovery from ACPI `_DSM`
- MIPI parameters (`MipiLanes`, `MipiPort`, `MipiDataFormat`, `MipiMBps`)
- power-on / power-off events and control-logic interfaces

So the earlier conclusion that the platform is blocked solely because `INT3472` exposes only one Linux-visible regulator is too strong. The board control path appears to involve additional ACPI/DSM-described data that Windows consumes but Linux does not currently use here.

## i2c verification

With `i2c-dev` loaded, `i2cdetect -y 2` shows an empty bus. The sensor at 0x36 is unreachable because AVDD is disabled and there is no userspace path to enable it (`CONFIG_REGULATOR_USERSPACE_CONSUMER` not set; direct sysfs write returns Permission Denied).

## What would be needed for Linux bring-up

1. A Linux `sc200pc` sensor driver, or a carefully adapted driver if `SC200PC` turns out to be a close variant of another supported sensor
2. Linux handling for the ACPI metadata Windows is using:
   - `_CRS`
   - `SSDB`
   - relevant `LNK0._DSM` interfaces
3. Matching IPU75XA graph / tuning integration for module `KAFC917`
4. Potentially additional PMIC / GPIO / control-logic plumbing once the sensor driver exists

Blindly forcing `L0SM` to a known OmniVision sensor ID is not a sound fix unless the underlying silicon and module wiring are proven compatible.

## References / related work

- [intel/ipu7-drivers](https://github.com/intel/ipu7-drivers) — kernel-side IPU7 support and reference sensor integration
- [intel/ipu7-camera-hal](https://github.com/intel/ipu7-camera-hal) — userspace HAL structure for IPU7 sensors
- [Microsoft Update Catalog search for `SSLC2000`](https://www.catalog.update.microsoft.com/Search.aspx?q=SSLC2000) — source used to retrieve the public Windows package for `ACPI\SSLC2000` / `sc200pc.inf` version `71.26100.0.11`
- Intel IPU7 ACPI camera sensor dispatch: `HCID()` / `GRID()` pattern in BIOS SSDT
