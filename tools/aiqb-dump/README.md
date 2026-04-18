# aiqb-dump

Host-side dumper for Intel CPFF / AIQB tuning binaries shipped by the
Windows IPU camera drivers.

Built initially for `SC200PC_KAFC917_PTL.aiqb` from the Samsung Galaxy
Book6 Pro OEM driver package (Microsoft Update Catalog,
`ACPI\SSLC2000` v71.26100.0.11). See `../../windows-camera-settings-plan.md`
for where this fits in the larger port plan, and
`../../camera-bringup-plan.md` for the overall Linux camera bring-up.

## Status (2026-04-18)

- v0 CPFF/AIQB container + metadata parser — **done**
- record-stream offset recovery after metadata padding — **done**
- r00 sensor info decoder — **done** (reproduces the kernel init table)
- r01 illuminant/gain table decoder — **partial decoder added**
- r07 quad-table decoder — **partial decoder added** (chromaticity-like anchors + coeff samples)
- r11 matrix-bank decoder — **partial decoder added** (supports both observed `header104` and `header100` layouts for banked 3×3 float matrices on a hue-like axis)
- one-pass cross-sensor compare mode — **done** (`--compare`, JSON output, plus compact `r11` bank statistics)
- LAIQ small-record config decoders — **partial decoders added**
- r01, r03, r05/r06 — **framing understood, semantics partial**
- CCM / AWB / LSC transplant into `sc200pc.yaml` — **TODO**

## Usage

All commands below use the SC200PC AIQB that already sits in this repo.
Substitute any other CPFF-container file to analyse a different sensor.

```
AIQB=../../packaging/sc200pc-ipu75xa-config/SC200PC_KAFC917_PTL.aiqb

# 1. Full dump — container tree + AIQB metadata + record table with
#    inline decoded fields for known record types. ~100 lines.
python3 aiqb-dump.py "$AIQB"

# 2. JSON version of the full dump, suitable for feeding into a
#    follow-up decoder or diffing against a reference AIQB.
python3 aiqb-dump.py "$AIQB" --json aiqb.json

# 3. Inspect a single record's bytes in hex + u16/u32/f32 views.
#    V = aiqb variant index (0 = main DFLT, 1 = LAIQ),
#    N = record index shown in the full dump (column [NN]).
#    If a decoder exists for that record type, the parsed structure is
#    printed before the raw byte views.
python3 aiqb-dump.py "$AIQB" --dump-record 0:5

# 4. Extract a record's raw payload to a file for external analysis.
python3 aiqb-dump.py "$AIQB" --extract-record 0:5:/tmp/r5.bin

# 5. Compare the main AIQB variant across several sensors in one pass.
python3 aiqb-dump.py --compare \
  "$AIQB" \
  /etc/camera/ipu75xa/IMX471_BBG803N3_PTL.aiqb \
  /etc/camera/ipu75xa/OV13B10_09B13_PTL.aiqb

# 6. Write that multi-sensor comparison as JSON.
python3 aiqb-dump.py --compare \
  "$AIQB" \
  /etc/camera/ipu75xa/IMX471_BBG803N3_PTL.aiqb \
  /etc/camera/ipu75xa/OV13B10_09B13_PTL.aiqb \
  --compare-json /tmp/aiqb-compare.json
```

The compare output now includes:
- compact `r01` illuminant summaries
- `r07` chromaticity-anchor summaries when present
- `r10` default-gain tuples
- LSC fingerprints for `0x0064/0x001c` / `0x0021`
- `r11` bank layout plus per-bank coefficient range, trace, determinant,
  and whether the last matrix ends with a zero-like tail coefficient

### Expected output shape for the full dump

```
container tree:
  CPFF   @0x000000  size=0x06dfec  payload=0x000018+0x06dfd4
    LCMC   @0x000018  ...
      DFLT   @0x000028  ...
        AIQB   @0x000038  ...
    LAIQ   @0x03c638  ...
      DFLT   @0x03c648  ...
        AIQB   @0x03c658  ...

aiqb[0] payload metadata:
  reserved0            = 0x00000000
  checksum             = 0xf39d6547
  metadata_len         = 0x00000a28
  record_count_hint    = 0x00000065
  version_marker       = 0x00000001
  build_time           = '251117020127997'
  pair_count           = 9
    IQStudio           = '25.46.3.0'
    LibIQ              = '2.0.359.0'
    CPU                = 'IPU75XA'
    Sensor             = 'SC202PC'
    ProjectName        = 'SC202PC_KAFC917_PTL.IPU75XA'
    ...
  records (17, covers 0x3bbc0/0x3bbc0 of record stream, tail=0x0):
    [ 0] @0x000a30  type=0x0066 flags=0x0002  len=0x000028
         preview=880740040f0002000a00000000000000
         decoded={'width': 1928, 'height': 1088, 'format_code': 15,
                  'mipi_lanes': 2, 'bits_per_pixel': 10}
    [ 1] @0x000a58  type=0x0064 flags=0x0003  len=0x000060
         decoded={'entry_count': 5, 'entries': [...], 'trailer_zero': 0}
    ...
```

`tail=0x0` on a successful parse means the record stream fully accounts
for the AIQB payload; any non-zero tail is a framing red flag.

## Container format

Outer tree (nested TLV):

```
CPFF  — whole file. 24-byte header: tag(4) + size(4) + 8×zero + 4×zero
                    + 4-byte checksum. Children follow immediately.
  LCMC — logical camera module container.
    DFLT — default variant.
      AIQB — tuning payload for the default mode.
  LAIQ — alternate AIQ variant (observed on SC200PC).
    DFLT
      AIQB — tuning payload for the secondary mode.
```

`LCMC`, `DFLT`, `AIQB`, `LAIQ` all use a **16-byte** header:
`tag(4) + size(4) + 8 reserved`. `size` always includes the header.

### AIQB payload layout

```
offset  size  field
------  ----  ------------------------------------------------
     0     4  reserved (zero)
     4     4  checksum / content id
     8     4  metadata_len  (bytes from 0x10 into the metadata block)
    12     2  record_count_hint
    14     2  version_marker
    16  meta  ASCII metadata block (bounded by metadata_len):
              - cstr  build_time   (YYMMDDHHMMSSmmm…)
              - cstr  default_comment
              - u16   pair_count
              - pair_count × (cstr key, cstr value)
              keys observed: IQStudio, LibIQ, ATE, CPU, Sensor,
                             ProjectName, Module, Comment, time
after   rest  binary record stream (4-byte aligned). Each record:
              - u32   length       (total bytes, incl. this header)
              - u16   record_type
              - u16   flags
              - u8    payload[length − 8]
```

The LAIQ variant carries a much smaller metadata block (no kv pairs) —
the parser bounds string reading with `metadata_len` so it doesn't
over-read. Some main variants also carry a few zero bytes after the
metadata block before the first record header; the tool now probes
forward to the first plausible aligned record stream automatically.

## Record decoder status

From the main-variant AIQB of `SC200PC_KAFC917_PTL.aiqb` (17 records,
247,280 bytes, framing covers 100% of the payload):

| # | type   | flags  | size    | status      | notes                                                                                   |
|---|--------|--------|---------|-------------|-----------------------------------------------------------------------------------------|
| 0 | 0x0066 | 0x0002 | 0x028   | **decoded** | `{width=1928, height=1088, format_code=15, mipi_lanes=2, bits_per_pixel=10}` — exact match vs kernel init table |
| 1 | 0x0064 | 0x0003 | 0x060   | partial     | Decoder now emits `entry_count`, per-entry `illuminant_code`, `u32 30000`, and `4×f16 gains`. Semantics are still inferred rather than pinned against Intel's parser. |
| 2 | 0x00c8 | 0x001f | 0x190   | unknown     |                                                                                          |
| 3 | 0x0066 | 0x000d | 0x058   | partial     | Pixel-array layout; 1928×1088 active area + 80×80 block (OB window?) + `0x3ff` (10-bit max). |
| 4 | 0x0065 | 0x0007 | 0x010   | stub        | Single u32 = 41.                                                                          |
| 5 | 0x0064 | 0x001c | 0x1cf38 | partial     | 118 KB LSC grid A. Header `5 4 63 47` ⇒ 5 CCTs × 4 channels × 63×47 × 2 B = 118440 + ~136 B prefix. First f32 = 0.9592. |
| 6 | 0x0064 | 0x0021 | 0x1cf38 | partial     | 118 KB LSC grid B (second CCT set or alternate mode).                                     |
| 7 | 0x0066 | 0x000f | 0x2a8   | partial     | Decoder now exposes a `u16[2]` header plus 83 `u16[4]` tuples. The leading 23 tuples contain 9 chromaticity-like anchor `(x, y)` pairs (first 7 repeated 3 times) with small companion coeff pairs. Still **not pinned** as CCM. |
| 8 | 0x0065 | 0x0011 | 0x010   | stub        | Single u32 = 1.                                                                           |
| 9 | 0x0064 | 0x0013 | 0x010   | stub        | Single u32 = 0.                                                                           |
|10 | 0x0066 | 0x0014 | 0x018   | stub        | u16s `(256, 256, 2049, 0, …)` — possibly default gains × 256.                              |
|11 | 0x0065 | 0x0019 | 0x1618  | partial     | Decoder exposes a banked `3×3` matrix table on a hue-like axis. SC200PC uses `bank_count=6` with a `header104` layout; IMX471 uses `bank_count=5` with a `header100` layout. This looks more like a hue-sector colour table than gamma. |
|12 | 0x0065 | 0x001a | 0x040   | unknown     | Starts with `0x0000803f 0x00000041 0x0000803f 0x00000041` = (1.0, 8.0, 1.0, 8.0) as f32.  |
|13 | 0x00c8 | 0x0009 | 0x020   | unknown     | 6 float32: (0.00082, 0.046, 0, 0, 24.22, 0). AE defaults?                                 |
|14 | 0x00c8 | 0x0022 | 0x150   | unknown     | 328 bytes.                                                                                |
|15 | 0x0064 | 0x0024 | 0x018   | stub        | u16s `(1, 8, 1, 1, …)`.                                                                   |
|16 | 0x0064 | 0x0025 | 0x010   | stub        | Single u32 = 2.                                                                           |

LAIQ variant (11 records, 24,616 bytes) carries different record types
(0x006a, 0x006b, 0x0067, 0x007c); probably a lower-resolution/power-save
mode. Small LAIQ records now decode as compact config tuples, which
helps distinguish generic mode metadata from the main-variant IQ tables.

## How to continue

Ordered from cheapest next step to most expensive. Pick whichever
matches the environment you have.

### A. On the Galaxy Book6 Pro (**preferred**)

`intel-ipu7-camera` installs Intel's closed-source `libia_cmc_parser` /
`libia_aiqb_parser`. A short C wrapper around
`ia_cmc_parser_init(data, size)` and `ia_aiq_init(...)` decodes every
record semantically without further RE. Check `/usr/include/ia_cmc_*`
and `/usr/lib/libia_*.so*` for the exact symbol/ABI, then:

1. Build a tiny tool (`tools/aiqb-dump/c/ia_cmc_dump.c`) that
   `mmap`s the `.aiqb`, calls `ia_cmc_parser_init`, and pretty-prints
   the returned `ia_cmc_t` struct (CCM, AWB, LSC, black level, gamma).
2. Diff the symbolic output against the raw-record dump from
   `aiqb-dump.py --dump-record` to pin each record type to its
   algorithm (e.g. "record type 0x0064 flags 0x001c == `cmc_lsc_t`").
3. Add a native Python decoder for each pinned record type, so the
   tool keeps working off-hardware for future sensors.

### B. Comparative RE against a known sensor

[`intel/ipu6-camera-bins`](https://github.com/intel/ipu6-camera-bins)
ships `.aiqb` files alongside libcamera-style tuning for sensors with
publicly-available IQ parameters (e.g. OV13B10, IMX471). Run
`aiqb-dump.py` on those and line up record types with the known
tuning values. Same record-type pinning as (A), slower.

### C. Pure-binary RE (fallback)

Without Intel libs and without a comparative AIQB, work one record at
a time with `--dump-record`:

- Small records (≤ 256 B): usually scalars / short arrays. Eyeball the
  f32 view for values in [−4, 4], the u16 view for small counts.
- Medium records (256 B – 10 KB): CCMs (9 f32 or 9 fixed-point per CCT),
  gamma LUTs (256 or 1024 entries), tone-mapping curves.
- Big records (≥ 100 KB): LSC grids. Reshape the u16 stream as
  `(CCTs, channels, grid_h, grid_w)` and plot — the per-channel gain
  maps should look smooth and roll off toward the corners.

For r05/r06 specifically: the grid dims 63×47 and layout
`5 CCTs × 4 channels` are already pinned; the u16 values are almost
certainly **Q8.8 fixed point** (so 0x0100 = 1.0, corner values ~0x01xx
– 0x02xx for 1.x–2.x gain).

## Regression test

The repo includes a small smoke test that pins the currently decoded
record layouts against the checked-in SC200PC AIQB:

```bash
python3 -m unittest tools/aiqb-dump/test_aiqb_dump.py
```

## Intel parser wrapper

On a machine with Intel's `ipu75xa` headers and libraries installed,
the repo now includes a small host-side wrapper that asks Intel's own
CMC parser to interpret the AIQB directly:

```bash
cc -O2 -Wall -Wextra \
  $(pkg-config --cflags ia_imaging-ipu75xa) \
  -o tools/aiqb-dump/c/ia_cmc_dump \
  tools/aiqb-dump/c/ia_cmc_dump.c \
  -L/usr/lib -lia_cmc_parser-ipu75xa

tools/aiqb-dump/c/ia_cmc_dump \
  ../../packaging/sc200pc-ipu75xa-config/SC200PC_KAFC917_PTL.aiqb
```

This is the fastest path to pinning whether the remaining records are
true `BlackLevel`, `ColorMatrices`, or `LSC` tables according to Intel's
own parser.

## Transplant target (once records are decoded)

`../../packaging/sc200pc-libcamera-pipewire/sc200pc.yaml` is the
libcamera simple-soft-IPA tuning. Algorithms the IPA supports:

- `BlackLevel` — `{r, gr, gb, b}` in 16-bit normalised units.
  Candidate source: small record with 4 u16 or u32 pedestal values.
- `Awb` — **no preset input**; the simple IPA estimates on the fly.
  The AWB record (r01) is informational only.
- `Ccm` — list of `{ct, ccm[9]}`. Source: r07 or similar 3×3-per-CCT
  record once dequantised.
- `Adjust`, `Agc` — default parameters, no AIQB data needed.

The simple soft IPA does **not** have a LSC algorithm today, so the
118 KB grids (r05/r06) only become useful if libcamera gains a soft
LSC step, or if we move the Galaxy Book6 Pro onto a full libcamera
pipeline handler. Treat LSC as lower priority.

## Pitfalls observed during RE

- The CPFF header is **24 bytes**, not 16 like every other tag —
  missing that made the initial parse return zero children.
- Empty strings are legal in the AIQB metadata (`Module` often has an
  empty value). Treating a zero-length string as a terminator breaks
  the pair walk; honour `pair_count` instead.
- The `metadata_len` field bounds the kv parse. Without that, the LAIQ
  variant over-reads into binary record bytes and produces garbage
  keys like `'\x0c\x01D'`.
- Record `length` is total-including-header. `length < 8` or
  `length % 4 != 0` or `length > remaining` means the framing is off.
- The "Sensor" key says **`SC202PC`**, not SC200PC — the driver-facing
  name and the IQ-facing name diverge. Don't treat this as a file
  mix-up.

## Licensing

Parser: CC0-1.0 (see SPDX header in `aiqb-dump.py`).
`.aiqb` binary: OEM content, **not** shipped in this repo; users need to
source it from the Windows driver package themselves.
