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

## What it does NOT do yet

Decode specific record types back into semantic values
(CCM / AWB / LSC / gamma / black level). That is the v1 goal — the
purpose of this v0 is to prove the framing is right and give us a
catalog of record types to attack.

## Usage

```
python3 aiqb-dump.py /path/to/file.aiqb [--json out.json]
```

Text output goes to stdout. `--json` writes a machine-readable dump
that a follow-up decoder can consume.

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
