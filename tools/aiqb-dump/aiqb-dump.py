#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
#
# Parse an Intel CPFF / AIQB container and dump its structure.
#
# Purpose: extract the inner tuning records from an Intel IPU AIQ binary
# (e.g. SC200PC_KAFC917_PTL.aiqb) without depending on Intel's closed
# runtime libraries, as a first step toward transplanting tuning values
# into a libcamera YAML.
#
# Scope today (v0):
#   * outer CPFF / LCMC / DFLT / AIQB nested TLV tree
#   * AIQB metadata header (sensor, project, tool versions, changelog)
#   * inner record scan with length/type framing + hex preview
#
# Scope later (v1+):
#   * decoders for the specific record types that back the libcamera
#     simple soft IPA (CCM, AWB, LSC grid, gamma, black level)
#
# Usage:
#   python3 aiqb-dump.py <path/to/file.aiqb> [--json out.json] [--records]

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# -- CPFF outer container -----------------------------------------------------

# The outer file is a nested tree of TLV containers. Each container has a
# header of 16 bytes, except the outermost "CPFF" container which has a
# 24-byte header (same 16 bytes plus 8 extra: a 4-byte zero field and a
# 4-byte checksum).
#
#   offset  size  field
#   ------  ----  -----------------------------------------------------------
#        0     4  tag (4 ASCII bytes, e.g. "CPFF", "LCMC", "DFLT", "AIQB")
#        4     4  size in bytes INCLUDING this header  (u32 LE)
#        8     8  reserved / version / uuid (varies per tag)
#       16     8  [CPFF only] zero + checksum
#
# The tree observed in SC200PC_KAFC917_PTL.aiqb (v71.26100.0.11):
#
#   CPFF            (whole file)
#     LCMC          (logical camera module container)
#       DFLT        (default variant)
#         AIQB      (raw AIQ payload for default mode)
#       LAIQ        (alternate AIQ variant)
#         DFLT
#           AIQB
#
# "AIQB" is both the file extension and an inner container tag. The raw
# tuning blob lives in the innermost "AIQB" payload.

CONTAINER_HEADER_SIZE = 16
CPFF_HEADER_SIZE = 24  # CPFF has 8 extra bytes before its first child
CONTAINER_TAGS = {b"CPFF", b"LCMC", b"DFLT", b"AIQB", b"LAIQ"}


@dataclass
class Container:
    tag: str
    offset: int
    size: int          # including header
    reserved: bytes    # 8 reserved bytes from the header
    children: list["Container"] = field(default_factory=list)
    # Payload offset/length excluding the 16-byte header:
    payload_offset: int = 0
    payload_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "offset": self.offset,
            "size": self.size,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "reserved_hex": self.reserved.hex(),
            "children": [c.to_dict() for c in self.children],
        }


def parse_container(buf: bytes, offset: int, end: int) -> Container | None:
    """Try to parse a CPFF-style container at offset. Return None if the
    bytes at offset don't look like a known container header."""
    if offset + CONTAINER_HEADER_SIZE > end:
        return None
    tag = bytes(buf[offset:offset + 4])
    if tag not in CONTAINER_TAGS:
        return None
    size = struct.unpack_from("<I", buf, offset + 4)[0]
    header_size = CPFF_HEADER_SIZE if tag == b"CPFF" else CONTAINER_HEADER_SIZE
    if size < header_size or offset + size > end:
        return None
    reserved = bytes(buf[offset + 8:offset + header_size])
    c = Container(
        tag=tag.decode("ascii"),
        offset=offset,
        size=size,
        reserved=reserved,
        payload_offset=offset + header_size,
        payload_size=size - header_size,
    )
    # The payload may itself start with a nested container. Walk children
    # while consecutive container headers fit within this payload.
    cur = c.payload_offset
    stop = offset + size
    while cur + CONTAINER_HEADER_SIZE <= stop:
        child = parse_container(buf, cur, stop)
        if child is None:
            break
        c.children.append(child)
        cur += child.size
    return c


def walk_containers(root: Container, depth: int = 0) -> list[tuple[int, Container]]:
    out = [(depth, root)]
    for child in root.children:
        out.extend(walk_containers(child, depth + 1))
    return out


# -- AIQB payload metadata ----------------------------------------------------

# The innermost AIQB payload begins with a 16-byte fixed header followed
# by an ASCII metadata block, then the binary record stream. Observed
# layout on SC200PC:
#
#   offset 0x00  u32     reserved (0)
#   offset 0x04  u32     checksum / content id
#   offset 0x08  u32     metadata block length (bytes 0x10 .. 0x10+len)
#   offset 0x0C  u16     record-count hint
#   offset 0x0E  u16     version marker
#
#   offset 0x10  cstr    build timestamp (17-digit YYMMDDHHMMSSmmm+)
#                cstr    default comment
#                u16     number of key/value pairs (N)
#                N x (cstr key, cstr value)   -- keys observed:
#                    IQStudio, LibIQ, ATE, CPU, Sensor, ProjectName,
#                    Module, Comment. "Comment" may hold a CRLF changelog.
#
# After the metadata block the stream resumes with a NUL-terminated "time"
# marker + timestamp, then binary records (see scan_records()).

def _read_cstr(payload: bytes, i: int) -> tuple[str, int]:
    end = payload.find(b"\x00", i)
    if end < 0:
        return "", len(payload)
    try:
        return payload[i:end].decode("utf-8"), end + 1
    except UnicodeDecodeError:
        return payload[i:end].decode("utf-8", errors="replace"), end + 1


def parse_aiqb_metadata(payload: bytes) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if len(payload) < 16:
        return meta
    meta["reserved0"] = struct.unpack_from("<I", payload, 0)[0]
    meta["checksum"] = struct.unpack_from("<I", payload, 4)[0]
    meta["metadata_len"] = struct.unpack_from("<I", payload, 8)[0]
    meta["record_count_hint"] = struct.unpack_from("<H", payload, 12)[0]
    meta["version_marker"] = struct.unpack_from("<H", payload, 14)[0]

    # The record stream starts after the metadata block. Observation:
    # records_offset for aiqb[0] (metadata_len=0x0a28) is 0xa30, which is
    # 8 bytes past `0x10 + (metadata_len - 0x10)` — the metadata block
    # includes the 16-byte fixed header. Bound scanning by it so variants
    # with tiny metadata blocks don't over-read into record data.
    meta_end = min(len(payload), meta["metadata_len"]) if meta["metadata_len"] else len(payload)
    # metadata_len < a few hundred bytes means this variant carries no
    # human-readable kv block — just the 16-byte header (aiqb[1]/LAIQ).
    if meta_end < 0x20:
        meta["records_offset"] = meta_end
        meta["kv"] = {}
        meta["kv_order"] = []
        return meta

    i = 16
    build_time, i = _read_cstr(payload, i)
    default_comment, i = _read_cstr(payload, i)
    meta["build_time"] = build_time
    meta["default_comment"] = default_comment

    if i + 2 > meta_end:
        meta["kv"] = {}
        meta["kv_order"] = []
        meta["records_offset"] = _align_up(i, 4)
        return meta
    pair_count = struct.unpack_from("<H", payload, i)[0]
    i += 2

    kv: dict[str, str] = {}
    order: list[tuple[str, str]] = []
    for _ in range(pair_count):
        if i >= meta_end:
            break
        key, i = _read_cstr(payload, i)
        if i >= meta_end:
            break
        value, i = _read_cstr(payload, i)
        kv[key] = value
        order.append((key, value))

    meta["pair_count"] = pair_count
    meta["kv"] = kv
    meta["kv_order"] = order
    meta["records_offset"] = _align_up(i, 4)
    return meta


def _align_up(n: int, align: int) -> int:
    return (n + align - 1) & ~(align - 1)


# -- Inner AIQB record scan ---------------------------------------------------

# After the metadata strings, the AIQB payload holds a stream of binary
# records. Empirically each record is framed as:
#
#   u32 length       (total bytes, including this 8-byte header)
#   u16 record_type
#   u16 flags        (subtype / version; often 2 or 3)
#   u8  payload[length - 8]
#
# Record type IDs appear to match Intel's internal CMC/AIQ tables (e.g.
# sensor info, AWB gain presets, CCM, LSC, gamma). Actual semantic
# decoding per-type is deferred to a follow-up — we just frame and
# catalog them here.

@dataclass
class Record:
    offset: int
    length: int
    record_type: int
    flags: int
    payload_preview_hex: str


def scan_records(payload: bytes, start: int,
                 preview_bytes: int = 16,
                 max_records: int = 4096) -> list[Record]:
    records: list[Record] = []
    cur = start
    end = len(payload)
    while cur + 8 <= end and len(records) < max_records:
        length = struct.unpack_from("<I", payload, cur)[0]
        rtype = struct.unpack_from("<H", payload, cur + 4)[0]
        flags = struct.unpack_from("<H", payload, cur + 6)[0]
        # Framing sanity: length must be >= header size, aligned to 4,
        # and not overrun the payload.
        if length < 8 or length % 4 != 0 or cur + length > end:
            break
        preview = bytes(payload[cur + 8:cur + 8 + min(preview_bytes,
                                                     length - 8)])
        records.append(Record(
            offset=cur,
            length=length,
            record_type=rtype,
            flags=flags,
            payload_preview_hex=preview.hex(),
        ))
        cur += length
    return records


# -- Output ------------------------------------------------------------------

def dump_text(path: Path, root: Container, buf: bytes) -> None:
    print(f"file: {path}")
    print(f"size: {len(buf)} bytes\n")
    print("container tree:")
    for depth, c in walk_containers(root):
        indent = "  " * depth
        print(f"  {indent}{c.tag:5s}  @0x{c.offset:06x}  "
              f"size=0x{c.size:06x}  "
              f"payload=0x{c.payload_offset:06x}+0x{c.payload_size:06x}")

    # Find every innermost AIQB container and dump its metadata + record
    # table. There are typically two (default and LAIQ variant).
    aiqbs = [c for depth, c in walk_containers(root)
             if c.tag == "AIQB" and not c.children]
    for i, c in enumerate(aiqbs):
        print()
        print(f"aiqb[{i}] payload metadata:")
        payload = bytes(buf[c.payload_offset:
                            c.payload_offset + c.payload_size])
        meta = parse_aiqb_metadata(payload)
        for key in ("reserved0", "checksum", "metadata_len",
                    "record_count_hint", "version_marker"):
            print(f"  {key:20s} = 0x{meta[key]:08x}")
        print(f"  records_offset       = 0x{meta.get('records_offset', 0):06x}")
        if "build_time" in meta:
            print(f"  build_time           = {meta['build_time']!r}")
        if "default_comment" in meta:
            print(f"  default_comment      = {meta['default_comment']!r}")
        if meta.get("pair_count") is not None:
            print(f"  pair_count           = {meta['pair_count']}")
        for k, v in meta.get("kv_order", []):
            short = v if len(v) < 72 else v[:69] + "..."
            print(f"    {k:18s} = {short!r}")
        # "Comment" often holds a multi-line changelog separated by CRLF.
        comment = meta.get("kv", {}).get("Comment", "")
        changelog = [line for line in comment.splitlines() if line.strip()]
        if changelog:
            print(f"  changelog ({len(changelog)} entries):")
            for line in changelog[:12]:
                print(f"    {line}")
            if len(changelog) > 12:
                print(f"    ... and {len(changelog) - 12} more")

        records = scan_records(payload, meta["records_offset"])
        covered = sum(r.length for r in records)
        tail = c.payload_size - (meta["records_offset"] + covered)
        print(f"  records ({len(records)}, covers "
              f"0x{covered:x}/0x{c.payload_size - meta['records_offset']:x} "
              f"of record stream, tail=0x{tail:x}):")
        for r in records[:40]:
            print(f"    @0x{r.offset:06x}  type=0x{r.record_type:04x} "
                  f"flags=0x{r.flags:04x}  len=0x{r.length:06x}  "
                  f"preview={r.payload_preview_hex}")
        if len(records) > 40:
            print(f"    ... and {len(records) - 40} more records")

        # Record-type histogram — quick way to confirm which tables are
        # present across AIQB variants.
        from collections import Counter
        hist = Counter(r.record_type for r in records)
        print("  record-type histogram:")
        for rtype, count in sorted(hist.items()):
            print(f"    type=0x{rtype:04x}  count={count}")


def dump_json(path: Path, root: Container, buf: bytes) -> dict[str, Any]:
    aiqbs = []
    for depth, c in walk_containers(root):
        if c.tag == "AIQB" and not c.children:
            payload = bytes(buf[c.payload_offset:
                                c.payload_offset + c.payload_size])
            meta = parse_aiqb_metadata(payload)
            records = scan_records(payload, meta["records_offset"])
            aiqbs.append({
                "offset": c.offset,
                "payload_offset": c.payload_offset,
                "payload_size": c.payload_size,
                "metadata": meta,
                "records": [
                    {
                        "offset": r.offset,
                        "length": r.length,
                        "record_type": r.record_type,
                        "flags": r.flags,
                        "payload_preview_hex": r.payload_preview_hex,
                    }
                    for r in records
                ],
            })
    return {
        "file": str(path),
        "size": len(buf),
        "container_tree": root.to_dict(),
        "aiqb_variants": aiqbs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, help="AIQB / CPFF file to parse")
    ap.add_argument("--json", type=Path,
                    help="write machine-readable JSON to this path")
    args = ap.parse_args()

    buf = args.path.read_bytes()
    root = parse_container(buf, 0, len(buf))
    if root is None or root.tag != "CPFF":
        print(f"{args.path}: not a CPFF container "
              f"(first 4 bytes: {buf[:4]!r})", file=sys.stderr)
        return 1

    dump_text(args.path, root, buf)

    if args.json is not None:
        data = dump_json(args.path, root, buf)
        args.json.write_text(json.dumps(data, indent=2))
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
