# aiqb-dump

Host-side dumper for Intel CPFF / AIQB tuning binaries shipped by the
Windows IPU camera drivers.

Built initially for `SC200PC_KAFC917_PTL.aiqb` from the Samsung Galaxy
Book6 Pro OEM driver package (Microsoft Update Catalog,
`ACPI\SSLC2000` v71.26100.0.11). See `windows-camera-settings-plan.md`
at the repo root for where this fits in the larger port plan.

## What it does today

- Parses the nested CPFF → LCMC → DFLT → AIQB container tree
- Extracts the AIQB metadata header (build timestamp, IQ toolchain
  versions, sensor/project name, version changelog)
- Scans the binary record stream after the metadata and reports each
  record's offset, type, flags, length, and a hex preview

The outermost "CPFF" container uses a 24-byte header; "LCMC", "DFLT",
"AIQB", and "LAIQ" use a 16-byte header. Each AIQB payload starts with
a 16-byte fixed header and an ASCII key/value metadata block bounded
by `metadata_len`; the binary record stream fills the remainder.

Each record is framed as `u32 length / u16 type / u16 flags / payload`,
where `length` includes the 8-byte header.

## Record decoders

Today the tool decodes one record fully, and provides a raw inspector
(`--dump-record`) for everything else so the remaining RE can proceed
side-by-side with a known-good AIQB on the target Galaxy Book6 Pro.

| rec | type   | flags  | size    | status       | notes |
| --- | ------ | ------ | ------- | ------------ | ----- |
|   0 | 0x0066 | 0x0002 | 0x28    | **decoded**  | sensor info: `{width=1928, height=1088, format_code=15, mipi_lanes=2, bits_per_pixel=10}` — matches the kernel init table exactly |
|   1 | 0x0064 | 0x0003 | 0x60    | partial      | 5×16 per-illuminant entries (flag codes 1/2/4/8/15, two float32s each, trailing `0x7530` marker). Likely AWB presets or chromaticity pairs. |
|   3 | 0x0066 | 0x000d | 0x58    | partial      | Pixel-array layout; contains active 1928×1088 and an 80×80 block (OB window?) plus `0x3ff` (1023 = 10-bit max). |
| 5/6 | 0x0064 | 0x001c, 0x0021 | 0x1cf38 | partial | LSC grid candidates. Leading u16s `5 4 63 47` ⇒ 5 CCTs × 4 channels × 63 × 47 × 2 bytes = 118440 bytes, + ~136 B prefix = 118576 total. First float32 value 0.9592 is a plausible LSC multiplier. |
|   7 | 0x0066 | 0x000f | 0x2a8   | unknown      | CCM candidate (672 bytes) but not in float32 form — probably fixed-point (Q1.15 or Q3.13). |
|  11 | 0x0065 | 0x0019 | 0x1618  | unknown      | 5648-byte table, possibly tone-mapping / gamma. |
|   * | other  | —      | small   | unknown      | Small scalar records (tile counts / enable flags). |

## RE tips

- Compare against a known-good AIQB shipped by
  [intel/ipu6-camera-bins](https://github.com/intel/ipu6-camera-bins)
  for a sensor with a Linux-side tuning file you can read. Matching
  record types + sizes across sensors narrows the algorithm attribution.
- On the target Galaxy Book6 Pro, Intel's runtime libs
  (`libia_aiqb_parser`, `libia_cmc_parser`, etc.) ship with
  `intel-ipu7-camera` and can decode records directly via
  `ia_cmc_parser_init`. A small C wrapper around those gives you exact
  semantic content.
- `--dump-record` shows the first 32 bytes as u16 / u32 / f32 side by
  side. For LSC-sized records, pipe the full extract through NumPy and
  reshape as `(CCTs, channels, grid_h, grid_w)` to visualize.

## Usage

```
# Full tree + metadata + record table:
python3 aiqb-dump.py /path/to/file.aiqb
python3 aiqb-dump.py /path/to/file.aiqb --json out.json

# Inspect one record across multiple interpretations (hex / u16 / u32 /
# f32). V = aiqb variant index (usually 0 = main, 1 = LAIQ), N = record
# index shown in the full dump.
python3 aiqb-dump.py /path/to/file.aiqb --dump-record 0:5

# Save a record's raw body for external analysis:
python3 aiqb-dump.py /path/to/file.aiqb --extract-record 0:5:/tmp/lsc.bin
```

## Known record types in SC200PC AIQB

From the default-mode (LCMC → DFLT → AIQB) variant of
`SC200PC_KAFC917_PTL.aiqb`:

| type   | count | notes                                           |
| ------ | ----- | ----------------------------------------------- |
| 0x0064 | 6     | mixed: a 118 KB + another 118 KB record likely backing the LSC grid, plus small metadata |
| 0x0065 | 4     | medium records, one ~5.5 KB                      |
| 0x0066 | 4     | small metadata (first record encodes 1928x1088) |
| 0x00c8 | 3     | small / mid records                              |

The LAIQ variant carries a different record set (types 0x006a, 0x006b,
0x0067, 0x007c, ...) and appears to be a secondary mode / resolution
profile.

## Licensing

The parser itself is CC0-1.0. The `.aiqb` binary it reads is OEM
content and is NOT shipped with this repo.
