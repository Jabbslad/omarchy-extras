# SC200PC Linux Bring-Up Plan for Galaxy Book6 Pro

## What is known

- ACPI camera device: `SSLC2000` on `\_SB.LNK0`
- ACPI device status: enabled (`_STA = 0x0f`)
- Camera module ID from `\_SB.LNK0._DDN`: `KAFC917`
- Camera resources from `\_SB.LNK0._CRS`:
  - controller: `\_SB.PC00.I2C3`
  - sensor address: `0x36`
  - likely second device: EEPROM at `0x50`
- Windows driver package:
  - `sc200pc.inf`
  - `sc200pc.sys`
  - `SC200PC_KAFC917_PTL.aiqb`
  - `SC200PC_KAFC917_PTL.cpf`
  - `graph_settings_SC200PC_KAFC917_PTL.bin`

The Windows INF explicitly identifies the sensor path as:

- `SC200PC camera sensor (ACPI\SSLC2000)`

## What the Windows binary suggests

Strings from `sc200pc.sys` show the driver expects:

- ACPI/DSM-driven I2C discovery
- GPIO control via names:
  - `Reset`
  - `Power0`
  - `Power1`
  - `gp_core_0%d`
- MIPI metadata:
  - `MipiLanes`
  - `MipiPort`
  - `MipiDataFormat`
  - `MipiMBps`
- EEPROM / NVM support:
  - `ReadModuleInfoFromEEPROM`
  - `NVMStartAddr`
  - `SensorID`

This means Linux bring-up is not just "add one more sensor ID". It likely needs:

- a new sensor driver
- ACPI metadata parsing beyond a trivial `_HID` match
- matching HAL / graph / tuning integration

## Recommended implementation order

## Current kernel status

The kernel-side graph integration is **resolved** as of 2026-04-17.

Path taken:

1. Patched `drivers/media/pci/intel/ipu-bridge.c` to add `SSLC2000` to
   `ipu_supported_sensors[]`
   ([patches/ipu-bridge-add-sslc2000.patch](patches/ipu-bridge-add-sslc2000.patch))
2. Shipped patched module as DKMS
   ([packaging/ipu-bridge-sslc2000/](packaging/ipu-bridge-sslc2000))
   installing into `/lib/modules/$(uname -r)/updates/dkms/` (takes
   priority over the in-tree `kernel/` copy)
3. Rebooted; module loads with the patched srcversion

Observed state after install:

- `intel-ipu7 0000:00:05.0: Found supported sensor SSLC2000:00`
- `intel-ipu7 0000:00:05.0: Connected 1 cameras`
- `intel_ipu7_isys ...: bind sc200pc 2-0036 nlanes is 2 port is 0`
- `intel_ipu7_isys ...: All sensor registration completed.`
- `/dev/media0` present
- `media-ctl -p` shows:
  ```
  entity 233: sc200pc 2-0036 (1 pad, 1 link)
    type V4L2 subdev subtype Sensor
    device node /dev/v4l-subdev4
    pad0: SOURCE
      [stream:0 fmt:SBGGR10_1X10/1600x1200 field:none colorspace:raw]
      -> "Intel IPU7 CSI2 0":0 [ENABLED,IMMUTABLE]
  ```

The prototype `sc200pc` driver still binds to `i2c-SSLC2000:00` with
probe-time reads succeeding at `0x36` (chip ID `0x0b7101`), but now
via the IPU7 async graph match rather than bare ACPI enumeration.

The remaining kernel-side work is streaming (see Phase 2, below),
not graph wiring.

### Phase 1: kernel probe only

Goal: bind a Linux sensor driver to `SSLC2000` and establish basic I2C communication.

1. Add a new driver skeleton, tentatively:
   - `drivers/media/i2c/sc200pc.c`
2. Match on ACPI ID:
   - `SSLC2000`
3. Probe resources from ACPI:
   - use the I2C client instantiated from `_CRS`
   - if needed, add helper logic to read `SSDB` and relevant `_DSM` data
4. Implement minimal power sequencing:
   - parse / request `Reset`, `Power0`, `Power1` if exposed through firmware helpers
   - support a simple `power_on -> identify -> power_off` path
5. Add chip-identification read:
   - look for likely chip ID registers / constants in `sc200pc.sys`
   - do not start with streaming

Success criteria:

- driver probes on `SSLC2000`
- I2C reads from `0x36` succeed
- chip ID or equivalent identity register is readable

Status:

- achieved

### Phase 2: media integration

Goal: register as a usable V4L2 subdevice.

1. Implement:
   - pad ops
   - format enumeration
   - mode table
   - stream on/off
2. Use conservative assumptions first:
   - single mode
   - default bus format from firmware / Windows hints
3. Validate that the media graph appears under IPU7

Success criteria:

- `media-ctl -p` shows the sensor
- IPU7 entities link correctly

Immediate prerequisite:

- either `ipu-bridge` must create software-node endpoints for `SSLC2000`
- or the same endpoint graph must be synthesized by a custom helper

Recommended approach:

- patch `ipu-bridge` first, not `sc200pc`
- this matches the existing `ipu7` fallback design and avoids duplicating bridge logic in the sensor driver

Status:

- graph integration: achieved (see "Current kernel status" above)
- pad ops, format enum, single default mode: achieved in prototype
  (1600×1200 `SBGGR10_1X10`)
- stream on/off: not yet implemented — still a placeholder in
  `sc200pc_s_stream`; needs register sequence reversed from
  `sc200pc.sys` or extracted from SmartSens documentation
- real mode table, controls (exposure, gain, test pattern): pending

### Phase 3: HAL / graph / tuning integration

Goal: make the sensor usable through the Intel IPU75XA userspace stack.

1. Add sensor config analogous to existing files under `/etc/camera/ipu75xa/sensors/`
2. Add `SC200PC` entry to `libcamhal_configs.json`
3. Install:
   - `graph_settings_SC200PC_KAFC917_PTL.bin`
   - `SC200PC_KAFC917_PTL.aiqb`
   - `SC200PC_KAFC917_PTL.cpf`
4. Wire the module name `KAFC917` into the config naming

Success criteria:

- userspace HAL can resolve graph and tuning assets
- camera enumerates through the IPU stack

Status (2026-04-17):

- `packaging/sc200pc-ipu75xa-config/` implemented; installs AIQB,
  sensor JSON (from `imx471-uf.json` template), registers
  `sc200pc-uf-0` in `libcamhal_configs.json`. PipeWire advertises
  "Hardware ISP Camera" via `/dev/video50`.
- **BLOCKED** on graph binary format. The Windows
  `graph_settings_SC200PC_KAFC917_PTL.bin` has magic `0x5C63B5E7`;
  the Linux `.IPU75XA.bin` format libcamhal expects has magic
  `0x4229ABEE`. Different containers — simple renaming doesn't help.
- IMX471 graph bin as stand-in gets further (scheduler demands
  `graphId 100005`, added locally to
  `/etc/camera/ipu75xa/pipe_scheduler_profiles.json`) but pipeline
  then fails at `GraphConfig: getPSysContextId: Can't find node` —
  the graph's PSYS DAG is IMX471-specific.
- Linux `.IPU75XA.bin` binaries are produced by Intel's proprietary
  `graphspec` compiler from XML; no SC200PC graph binary is known
  to exist on Linux.
- HAL also calls `SetControl` on the sc200pc subdev for controls
  the driver doesn't yet expose (exposure, gain, HFLIP/VFLIP, test
  pattern). Errors are survivable but should be fixed.

Paths forward:

1. Obtain the SC200PC Linux graph binary via Samsung/Intel upstream
   contact.
2. Switch Omarchy's userspace camera stack to `libcamera` (YAML
   pipeline descriptions, no pre-compiled graph bins).
3. Use raw V4L2 (`/dev/video0`) directly for apps that can handle
   Bayer raw with software debayer. No HAL, no 3A, no tuning, no
   ISP — only suitable for dev/test.

## Initial Linux driver shape

The first version of `sc200pc.c` should include:

- ACPI match table with `SSLC2000`
- `v4l2_subdev` integration
- runtime PM hooks
- power helper stubs
- register read/write helpers
- a tiny mode table placeholder
- identify routine

The first implementation should avoid:

- autofocus
- EEPROM parsing beyond minimal module ID checks
- full control support
- multiple modes
- image-quality tuning

## Open technical questions

1. Is `SC200PC` the final silicon name, or is it a driver-facing name for a closely related internal sensor family?
2. Why do Windows tuning assets include `SC202PC` strings while the INF and SYS name `SC200PC`?
3. Which parts of `LNK0._DSM` are required for probe, and which are only used for richer board integration?
4. Are `Reset`, `Power0`, and `Power1` reachable through existing Linux GPIO / INT3472 plumbing, or is a new ACPI helper needed?

## Highest-value next reverse-engineering tasks

1. ~~Patch `ipu-bridge` to accept `SSLC2000`~~ — **done**
   ([patches/ipu-bridge-add-sslc2000.patch](patches/ipu-bridge-add-sslc2000.patch),
   [packaging/ipu-bridge-sslc2000/](packaging/ipu-bridge-sslc2000))
2. ~~Confirm `secondary` fwnode graph after `ipu_bridge_init()`~~ —
   **done**; `sc200pc 2-0036` is now an `ENABLED,IMMUTABLE` link to
   `Intel IPU7 CSI2 0:0`
3. ~~Reverse-engineer the `sc200pc` stream-on register sequence~~ —
   **done**; 141-entry init table extracted from the OEM Windows
   `sc200pc.sys` (`.rdata` offset `0x670`+, 16-byte entries
   `{u32 op=1, u32 addr, u32 value, u32 reserved}`). Shipped in
   `packaging/sc200pc-dkms/` 0.3.0. Verified by capturing real
   4 247 552-byte Bayer BGGR raw10 frames from `/dev/video0`.
4. ~~Build IPU75XA userspace config~~ — **partial**.
   `packaging/sc200pc-ipu75xa-config/` installs AIQB + sensor JSON +
   `libcamhal_configs.json` registration. Graph binary
   (`.IPU75XA.bin`) incompatible with Linux libcamhal — see Phase 3
   Status above. HAL pipeline does not complete.
5. Add exposure / analog gain / HFLIP / VFLIP / test pattern
   V4L2 controls to the sc200pc driver. Registers known:
   `0x3e00`–`0x3e02` exposure, `0x3e09` analog gain, `0x3221`
   flip/mirror.
6. (Optional) Decode `SSDB` payload from runtime ACPI to verify
   `nlanes=2, port=0` against SSDB bytes (not necessary for current
   operation, but useful for the upstream patch description).
7. Pick a strategy for the HAL blocker: (a) Samsung/Intel contact to
   obtain the Linux graph binary, (b) libcamera migration, or
   (c) leave camera on raw V4L2 path only.
8. Wire `install.sh` to install `ipu-bridge-sslc2000`, `sc200pc-dkms`,
   and `sc200pc-ipu75xa-config` once (7) is resolved.
