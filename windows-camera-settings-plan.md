# Porting Windows SC200PC Camera Settings to Linux

Working branch: `claude/port-camera-settings-linux-3T6mx`

This doc tracks how each category of "Windows camera settings" on the
Galaxy Book6 Pro (`ACPI\SSLC2000`, module `KAFC917`) maps onto something
Linux can consume. It is the companion to `camera-bringup-plan.md` and
focuses specifically on extraction and transplant — not kernel graph
wiring, which is already solved.

## Source package

- Microsoft Update Catalog, search term `SSLC2000`
- Hardware ID `ACPI\SSLC2000`, package version `71.26100.0.11` (2025-11-16)
- Update GUID `aa876ff4-ff3e-4690-849b-6839f5791817`
- 27.7 MB CAB; relevant payload:
  - `sc200pc.sys` — kernel driver
  - `sc200pc.inf` — device metadata
  - `SC200PC_KAFC917_PTL.aiqb` — Intel AIQ tuning (~440 KB)
  - `SC200PC_KAFC917_PTL.cpf` — camera parameter file
  - `graph_settings_SC200PC_KAFC917_PTL.bin` — IPU graph (Windows format)

## Asset-by-asset plan

### 1. Sensor I2C init registers (`sc200pc.sys`)

- Layout: `.rdata + 0x670`, 141 × 16-byte entries
  `{u32 op=1, u32 addr, u32 value, u32 reserved}`, terminator `addr=0xffff`.
- **Status: DONE.** Transcribed into
  `packaging/sc200pc-dkms/sc200pc.c:97` as `sc200pc_1928x1088_raw10_30fps[]`.
- No further action.

### 2. AIQ tuning (`SC200PC_KAFC917_PTL.aiqb`) — **active target**

Intel IPU AIQ binary. Same container across IPU3/IPU6/IPU7 (public
parsers exist in `intel/ipu6-camera-hal`, `intel/ipu7-camera-hal`,
`libcamhal`). Contains the tables that matter most for the current
"olive cast" symptom on the libcamera native path
(`camera-issue-report.md:22-28`):

- Colour Correction Matrix (CCM) per colour temperature
- Auto White Balance presets (gains per illuminant)
- Lens Shading Correction grid (LSC)
- Gamma LUT
- Black level pedestal
- Defect Pixel Correction thresholds
- Tone mapping curves

Target: transplant CCM + AWB + LSC + gamma into
`packaging/sc200pc-libcamera-pipewire/sc200pc.yaml`, which today holds
only hand-tuned 3200 K and 6500 K CCMs
(`sc200pc-libcamera-pipewire/sc200pc.yaml:25-34`).

Work plan:

1. Inspect `.aiqb` magic and version; identify which of the public
   Intel parsers matches. **DONE** — magic is `CPFF` (Intel Camera
   Parameter File Format). Container tree and record framing are
   documented below. No public parser was usable, so we wrote our own
   clean-room parser.
2. Stand up a host-side extractor. **DONE (v0)** — see
   `tools/aiqb-dump/`. It parses the CPFF tree, extracts the AIQB
   metadata block (IQ toolchain versions, sensor name, build
   timestamp, version changelog), and enumerates the binary record
   stream with 100% framing coverage (no tail bytes on either AIQB
   variant of `SC200PC_KAFC917_PTL.aiqb`).
3. Decode specific record types → JSON (CCM, AWB, LSC, gamma, black
   level). **TODO** — this is the next iteration.
4. Cherry-pick the records needed for the libcamera simple soft IPA
   and rewrite `sc200pc.yaml`.
5. Validate with the existing `sc200pc-libcamera-check` script and
   a qualitative check (no olive cast indoors).

### Reverse-engineered container format (from
`SC200PC_KAFC917_PTL.aiqb` v71.26100.0.11)

Outer tree (nested TLV):

- `CPFF` (24-byte header: tag + size + 8 zero + 4 zero + 4 checksum)
  - `LCMC` (16-byte header)  — logical camera module container
    - `DFLT` — default variant
      - `AIQB` — default-mode tuning blob
  - `LAIQ` — alternate / secondary AIQ variant
    - `DFLT`
      - `AIQB` — secondary-mode tuning blob

Each AIQB payload:

- 16-byte fixed header: `u32 reserved / u32 checksum / u32
  metadata_len / u16 record_count_hint / u16 version_marker`
- ASCII metadata block (only in the main variant; bounded by
  `metadata_len`): build timestamp cstr, default-comment cstr, `u16
  pair_count`, then `pair_count × (key cstr, value cstr)`. Keys seen:
  `IQStudio`, `LibIQ`, `ATE`, `CPU`, `Sensor`, `ProjectName`,
  `Module`, `Comment`, `time`.
- Binary record stream: repeating `u32 length / u16 type / u16 flags
  / payload[length-8]`.

Record type distribution in the main AIQB (17 records, 247,280 bytes):

- 0x0064 ×6 — includes two 118 KB records (likely LSC grids per CCT)
- 0x0065 ×4 — includes a ~5.5 KB record
- 0x0066 ×4 — first one at 40 bytes encodes `1928×1088`, likely
  sensor geometry / mode info
- 0x00c8 ×3 — small/medium

Next-step decoding needs to map these type codes to the AIQ algorithm
tables (CCM, AWB, LSC, gamma, tone-mapping, black level, DPC). The
two 118 KB records at type 0x0064 are the most interesting LSC
candidates; the small ≤ 96-byte records at type 0x0064 and 0x0066 are
the most interesting CCM / WB candidates.

"Sensor" key says `SC202PC`, not SC200PC — confirming open question 2
in `camera-bringup-plan.md` (the driver-facing name is
interchangeably `SC200PC` / `SC202PC` across the Windows assets).

Changelog in the metadata gives a rough read of what Samsung/Intel
cared about while tuning, e.g. "fine tune AWB preferred color",
"finetune ACM for D50/F2/F11", "enable flicker detection V2", which
is a useful hint for which tables matter most for the olive-cast
symptom.

Licensing: `.aiqb` is OEM content, kept out of the repo. The extractor
tool and its JSON output can be public; the `.yaml` we emit is a
derived tuning, which is the same status as any chart-calibrated
libcamera YAML and fine to ship.

### 3. Camera Parameter File (`SC200PC_KAFC917_PTL.cpf`)

Usually a companion to the AIQB (lens characterisation, module-specific
offsets). Parse only if (2) proves insufficient — the libcamera soft
IPA does not consume a separate CPF.

### 4. Windows IPU graph binary
(`graph_settings_SC200PC_KAFC917_PTL.bin`)

- Container magic `0x5C63B5E7` vs Linux `.IPU75XA.bin` magic
  `0x4229ABEE` (`camera-bringup-plan.md:180-191`).
- Different format, produced by Intel's proprietary `graphspec`
  compiler from XML. No conversion path exists.
- **Decision: abandon this path.** Document it in the camera docs
  and do not treat the HAL route as something we can unblock with
  the CAB contents alone. The kernel+libcamera path already gives
  working frames.

### 5. INF / driver strings (`sc200pc.inf`, `sc200pc.sys`)

Contains:

- `MipiLanes=2`, `MipiPort=0`, `MipiDataFormat`, `MipiMBps`
- GPIO names (`Reset`, `Power0`, `Power1`)
- Sensor control min/max/default hints exposed to the Windows
  camera pipeline

Most of this is already recovered via ACPI/SSDB at runtime. The one
place it's still useful is for setting the **min/max/default/step**
of the V4L2 controls the driver is growing (exposure `0x3e00-0x3e02`,
analogue gain `0x3e09`, flip `0x3221`, test pattern). Pull those
triples rather than guessing them.

## Out of scope (for this branch)

- HAL / icamerasrc integration
- Kernel graph bringup changes
- Autofocus, EEPROM ID validation
- Chart-based recalibration; we're porting, not recapturing

## Next actions

1. ~~Inspect `.aiqb` header + pick a parser strategy.~~ **done**
2. ~~Stand up AIQB dumper (v0 framing).~~ **done** — see
   `tools/aiqb-dump/`
3. Decode record type 0x0066 (sensor/mode info) and 0x0064 small
   records (likely CCM / black level / geometry). Smallest records
   first — they're the easiest to validate.
4. Decode record type 0x0064 118 KB records (LSC). Needs grid
   dimensions, which likely come from one of the small metadata
   records.
5. Transplant records into `sc200pc.yaml` algorithms: BlackLevel,
   Awb, Ccm, LensShading (if libcamera simple soft IPA supports it).
6. Validate with `sc200pc-libcamera-check` and qualitative indoor
   capture.
