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
import collections
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


# -- Record decoders ---------------------------------------------------------

# Confidence scale used below:
#   high   — cross-checked against known sensor facts (resolution, lanes)
#   medium — values are plausible but exact semantics not pinned
#   low    — best-guess framing only
#
# Today only the sensor-info record is "high" confidence. The rest are
# left to the raw inspector (dump_record_views) so RE on the target
# Galaxy Book6 Pro can continue alongside a known-good AIQB from
# intel/ipu6-camera-bins to cross-reference.


def decode_sensor_info(body: bytes) -> dict[str, Any] | None:
    """Decode a type=0x0066 flags=0x0002 sensor-info record.

    Layout (confidence: high — matches 1928x1088 2-lane 10-bit observed
    on SC200PC, and the kernel init table):

        offset  size  field
             0     2  active width  (u16)
             2     2  active height (u16)
             4     2  format code?  (u16)       -- 0x000f observed
             6     2  MIPI lane count (u16)
             8     2  bits per pixel (u16)
            10  rest  padding (zero)
    """
    if len(body) < 10:
        return None
    width, height, fmt_code, lanes, bpp = struct.unpack_from("<5H", body, 0)
    return {
        "width": width,
        "height": height,
        "format_code": fmt_code,
        "mipi_lanes": lanes,
        "bits_per_pixel": bpp,
    }


def decode_awb_illuminants(body: bytes) -> dict[str, Any] | None:
    """Decode a type=0x0064 flags=0x0003 illuminant/gain table.

    Layout (confidence: medium):

        offset  size  field
             0     2  entry_count (u16)      -- 5 on SC200PC
             2     2  reserved (u16)
             4  count * 16 bytes:
                       u32 exposure_like      -- 30000 on every entry
                       u16 reserved
                       u16 illuminant_code
                       4 x f16 gains
      after entries  4  trailer_zero (u32)

    The f16 quadruplets are plausible per-illuminant gain presets
    because they cluster around 1.5-2.3 and the illuminant codes repeat
    across the five entries in a stable table.
    """
    if len(body) < 8 or (len(body) - 8) % 16 != 0:
        return None
    entry_count, reserved0 = struct.unpack_from("<HH", body, 0)
    expected_len = 8 + entry_count * 16
    if len(body) != expected_len:
        return None

    entries: list[dict[str, Any]] = []
    cur = 4
    for _ in range(entry_count):
        exposure_like = struct.unpack_from("<I", body, cur)[0]
        reserved = struct.unpack_from("<H", body, cur + 4)[0]
        illuminant_code = struct.unpack_from("<H", body, cur + 6)[0]
        gains = struct.unpack_from("<4e", body, cur + 8)
        entries.append({
            "exposure_like": exposure_like,
            "reserved": reserved,
            "illuminant_code": illuminant_code,
            "gains": [round(v, 6) for v in gains],
        })
        cur += 16

    trailer_zero = struct.unpack_from("<I", body, cur)[0]
    return {
        "entry_count": entry_count,
        "reserved0": reserved0,
        "trailer_zero": trailer_zero,
        "entries": entries,
    }


def decode_single_u32(body: bytes, field: str = "value") -> dict[str, Any] | None:
    if len(body) != 8:
        return None
    value, trailer_zero = struct.unpack_from("<II", body, 0)
    return {field: value, "trailer_zero": trailer_zero}


def decode_default_gains(body: bytes) -> dict[str, Any] | None:
    if len(body) != 16:
        return None
    values = struct.unpack_from("<8H", body, 0)
    return {
        "u16": list(values),
        "gain_x256": [round(v / 256.0, 6) for v in values[:3]],
    }


def decode_constant_f32_table(body: bytes) -> dict[str, Any] | None:
    if len(body) == 0 or len(body) % 4 != 0:
        return None
    values = struct.unpack_from("<" + "f" * (len(body) // 4), body)
    hist = collections.Counter(round(v, 6) for v in values)
    return {
        "values": [round(v, 6) for v in values],
        "value_histogram": dict(sorted(hist.items())),
    }


def decode_six_f32(body: bytes) -> dict[str, Any] | None:
    if len(body) != 24:
        return None
    values = struct.unpack_from("<6f", body, 0)
    return {"values": [round(v, 6) for v in values]}


def decode_u16_tuple(body: bytes) -> dict[str, Any] | None:
    if len(body) == 0 or len(body) % 2 != 0:
        return None
    return {"u16": list(struct.unpack_from("<" + "H" * (len(body) // 2), body))}


def decode_chromaticity_quad_table(body: bytes) -> dict[str, Any] | None:
    """Decode a type=0x0066 flags=0x000f quad table.

    Layout (confidence: low/medium):

        u16 header_count   -- 7 on SC200PC
        u16 header_mode    -- 2 on SC200PC
        repeated u16[4] tuples
        u16 trailer_zero[2]

    The leading tuples look like repeated chromaticity anchors because
    the first two values fall into plausible x/y ranges when normalised
    by 65535. Each anchor then carries a small companion pair that varies
    across repeats. This is useful RE structure, but not enough to call
    the record a CCM table yet.
    """
    if len(body) < 12 or len(body) % 4 != 0:
        return None
    vals = struct.unpack_from("<" + "H" * (len(body) // 2), body)
    if (len(vals) - 2) % 4 != 2:
        return None

    header_count, header_mode = vals[:2]
    trailer_zero = list(vals[-2:])
    quads = [tuple(vals[i:i + 4]) for i in range(2, len(vals) - 2, 4)]
    if not quads:
        return None

    anchor_quads = []
    for quad in quads:
        x, y, a, b = quad
        if x <= 4096 or y <= 4096:
            break
        anchor_quads.append(quad)

    grouped: list[dict[str, Any]] = []
    seen_xy: set[tuple[int, int]] = set()
    for x, y, a, b in anchor_quads:
        xy = (x, y)
        if xy in seen_xy:
            continue
        samples = [[qa, qb] for qx, qy, qa, qb in anchor_quads if (qx, qy) == xy]
        grouped.append({
            "x_u16": x,
            "y_u16": y,
            "x_norm": round(x / 65535.0, 6),
            "y_norm": round(y / 65535.0, 6),
            "sample_count": len(samples),
            "coeff_samples": samples,
        })
        seen_xy.add(xy)

    return {
        "header_count": header_count,
        "header_mode": header_mode,
        "quad_count": len(quads),
        "trailer_zero": trailer_zero,
        "anchor_quad_count": len(anchor_quads),
        "anchor_point_count": len(grouped),
        "anchor_points": grouped,
        "tail_quad_count": len(quads) - len(anchor_quads),
    }


def decode_matrix_bank_table(body: bytes) -> dict[str, Any] | None:
    """Decode a type=0x0065 flags=0x0019 matrix-bank table.

    Layout (confidence: medium):

        u16 bank_count      -- 6 on SC200PC
        u16 header_floats   -- 24 on SC200PC
        u32 axis[24]        -- 15..360 in 15-degree steps
        u32 bank_count_dup  -- 6 on SC200PC
        bank_count * (
            f32 header[6] +
            25 * f32 matrix[9]
        )

    This does not look like gamma data. The `15..360` axis and the
    repeated 3x3 float matrices are a better fit for a hue-sector colour
    correction table (ACM/CCM-like) than a scalar tone curve.
    """
    if len(body) < 100:
        return None

    bank_count, axis_count_hint = struct.unpack_from("<HH", body, 0)
    axis = list(struct.unpack_from("<24I", body, 4))
    if bank_count == 0:
        return None

    # IPU75XA main-variant records of this family come in at least two
    # closely related layouts:
    #   - SC200PC: 0x68-byte header, duplicate bank count at +0x64
    #   - IMX471: 0x64-byte header, no matching duplicate bank count
    #
    # In both cases the payload still resolves to N banks of 6 header
    # floats + K 3x3 matrices. Try the more explicit layout first.
    layouts = [("header100", 100, None)]
    if len(body) >= 104:
        bank_count_dup = struct.unpack_from("<I", body, 100)[0]
        if bank_count_dup == bank_count:
            layouts.insert(0, ("header104", 104, bank_count_dup))
        else:
            layouts.append(("header104", 104, bank_count_dup))

    chosen = None
    for layout_name, header_size, bank_count_dup in layouts:
        float_bytes = len(body) - header_size
        if float_bytes <= 0 or float_bytes % 4 != 0:
            continue
        float_count = float_bytes // 4
        if float_count % bank_count != 0:
            continue
        bank_len = float_count // bank_count
        if bank_len < 6 or (bank_len - 6) % 9 != 0:
            continue
        matrix_count = (bank_len - 6) // 9
        chosen = (layout_name, header_size, bank_count_dup, float_count, bank_len, matrix_count)
        break

    if chosen is None:
        return None

    layout_name, header_size, bank_count_dup, float_count, bank_len, matrix_count = chosen
    floats = struct.unpack_from("<" + "f" * float_count, body, header_size)

    banks: list[dict[str, Any]] = []
    for i in range(bank_count):
        blk = floats[i * bank_len:(i + 1) * bank_len]
        header = [round(v, 6) for v in blk[:6]]
        matrices = [
            [round(v, 6) for v in blk[6 + j * 9:6 + (j + 1) * 9]]
            for j in range(matrix_count)
        ]
        banks.append({
            "header": header,
            "matrix_count": matrix_count,
            "matrix0": matrices[0],
            "matrix1": matrices[1] if matrix_count > 1 else None,
            "matrix_last": matrices[-1],
        })

    return {
        "bank_count": bank_count,
        "axis_count_hint": axis_count_hint,
        "axis": axis,
        "layout": layout_name,
        "header_size": header_size,
        "bank_count_dup": bank_count_dup,
        "matrix_count_per_bank": matrix_count,
        "bank_summary": banks,
    }


def find_record_stream_start(payload: bytes, start: int,
                             max_seek: int = 64) -> int:
    """Find the first plausible record stream offset near `start`.

    Some AIQBs carry a few zero bytes after the metadata block before the
    first u32 record length. Prefer the earliest aligned offset that
    yields at least one valid record and the largest covered byte count.
    """
    aligned_start = _align_up(start, 4)
    best_offset = aligned_start
    best_count = -1
    best_covered = -1
    for off in range(aligned_start, min(len(payload), aligned_start + max_seek) + 1, 4):
        records = scan_records(payload, off)
        covered = sum(r.length for r in records)
        if not records:
            continue
        if len(records) > best_count or (len(records) == best_count and covered > best_covered):
            best_offset = off
            best_count = len(records)
            best_covered = covered
    return best_offset


def get_aiqb_variants(root: Container) -> list[Container]:
    return [c for _d, c in walk_containers(root) if c.tag == "AIQB" and not c.children]


def get_aiqb_records(buf: bytes, c: Container) -> tuple[bytes, dict[str, Any], list[Record]]:
    payload = bytes(buf[c.payload_offset:c.payload_offset + c.payload_size])
    meta = parse_aiqb_metadata(payload)
    records_offset = find_record_stream_start(payload, meta["records_offset"])
    meta["records_offset"] = records_offset
    records = scan_records(payload, records_offset)
    return payload, meta, records


def _record_key(record: Record) -> tuple[int, int]:
    return record.record_type, record.flags


def _round_list(values: list[float], limit: int | None = None) -> list[float]:
    seq = values if limit is None else values[:limit]
    return [round(v, 6) for v in seq]


def matrix_trace(mat: list[float]) -> float:
    return round(mat[0] + mat[4] + mat[8], 6)


def matrix_determinant(mat: list[float]) -> float:
    a, b, c, d, e, f, g, h, i = mat
    det = (
        a * (e * i - f * h)
        - b * (d * i - f * g)
        + c * (d * h - e * g)
    )
    return round(det, 6)


def bank_matrix_stats(bank: dict[str, Any]) -> dict[str, Any]:
    mats = [
        bank["matrix0"],
        *([bank["matrix1"]] if bank.get("matrix1") is not None else []),
        bank["matrix_last"],
    ]
    flat = [v for mat in mats for v in mat]
    matrix0 = bank["matrix0"]
    matrix_last = bank["matrix_last"]
    return {
        "coeff_min": round(min(flat), 6),
        "coeff_max": round(max(flat), 6),
        "matrix0_trace": matrix_trace(matrix0),
        "matrix0_det": matrix_determinant(matrix0),
        "matrix_last_trace": matrix_trace(matrix_last),
        "matrix_last_det": matrix_determinant(matrix_last),
        "matrix_last_tail_zero": abs(matrix_last[-1]) < 1e-6,
    }


def lsc_fingerprint(body: bytes) -> dict[str, Any] | None:
    if len(body) < 32:
        return None
    dims = list(struct.unpack_from("<4H", body, 16))
    prefix_u32 = list(struct.unpack_from("<8I", body, 0))
    first_gain = round(struct.unpack_from("<f", body, 28)[0], 6)
    return {
        "payload_len": len(body),
        "prefix_u32": prefix_u32,
        "dims_u16": dims,
        "first_gain_f32": first_gain,
    }


def build_compare_summary(path: Path, variant: int = 0) -> dict[str, Any]:
    buf = path.read_bytes()
    root = parse_container(buf, 0, len(buf))
    if root is None or root.tag != "CPFF":
        raise ValueError(f"{path}: not a CPFF container")

    aiqbs = get_aiqb_variants(root)
    if variant < 0 or variant >= len(aiqbs):
        raise IndexError(f"{path}: no AIQB variant {variant}")

    c = aiqbs[variant]
    payload, meta, records = get_aiqb_records(buf, c)
    by_key = {_record_key(r): (r, payload[r.offset + 8:r.offset + r.length]) for r in records}

    summary: dict[str, Any] = {
        "path": str(path),
        "variant": variant,
        "sensor": meta.get("kv", {}).get("Sensor", path.stem),
        "records_offset": meta["records_offset"],
        "record_count": len(records),
        "record_keys": [f"0x{r.record_type:04x}/0x{r.flags:04x}" for r in records],
    }

    sensor_info = by_key.get((0x0066, 0x0002))
    if sensor_info is not None:
        summary["sensor_info"] = decode_record(0x0066, 0x0002, sensor_info[1])

    awb = by_key.get((0x0064, 0x0003))
    if awb is not None:
        decoded = decode_record(0x0064, 0x0003, awb[1])
        if decoded is not None:
            summary["r01_awb"] = {
                "entry_count": decoded["entry_count"],
                "illuminant_codes": [entry["illuminant_code"] for entry in decoded["entries"]],
                "gain0_first3": [_round_list(entry["gains"], 3) for entry in decoded["entries"][:3]],
            }

    chroma = by_key.get((0x0066, 0x000F))
    if chroma is None:
        chroma = by_key.get((0x0065, 0x000F))
    if chroma is not None:
        decoded = decode_record(chroma[0].record_type, chroma[0].flags, chroma[1])
        if decoded is not None:
            anchors = decoded.get("anchor_points", [])
            summary["r07_chromaticity"] = {
                "key": f"0x{chroma[0].record_type:04x}/0x{chroma[0].flags:04x}",
                "header_count": decoded["header_count"],
                "header_mode": decoded["header_mode"],
                "quad_count": decoded["quad_count"],
                "anchor_point_count": decoded["anchor_point_count"],
                "tail_quad_count": decoded["tail_quad_count"],
                "anchor_xy_first3": [
                    [anchor["x_norm"], anchor["y_norm"]]
                    for anchor in anchors[:3]
                ],
            }

    default_gains = by_key.get((0x0066, 0x0014))
    if default_gains is not None:
        decoded = decode_record(0x0066, 0x0014, default_gains[1])
        if decoded is not None:
            summary["r10_default_gains"] = {
                "u16": decoded["u16"][:4],
                "gain_x256": decoded["gain_x256"],
            }

    matrix = by_key.get((0x0065, 0x0019))
    if matrix is not None:
        decoded = decode_record(0x0065, 0x0019, matrix[1])
        if decoded is not None:
            bank0 = decoded["bank_summary"][0]
            summary["r11_matrix_bank"] = {
                "layout": decoded["layout"],
                "header_size": decoded["header_size"],
                "bank_count": decoded["bank_count"],
                "axis_first5": decoded["axis"][:5],
                "axis_last3": decoded["axis"][-3:],
                "matrix_count_per_bank": decoded["matrix_count_per_bank"],
                "bank0_header": bank0["header"],
                "bank0_matrix0": bank0["matrix0"],
                "bank0_matrix_last": bank0["matrix_last"],
                "bank_stats": [
                    {
                        "bank": idx,
                        "header": bank["header"],
                        **bank_matrix_stats(bank),
                    }
                    for idx, bank in enumerate(decoded["bank_summary"])
                ],
            }

    lsc_records = []
    for key in ((0x0064, 0x001c), (0x0064, 0x0021)):
        rec = by_key.get(key)
        if rec is None:
            continue
        fp = lsc_fingerprint(rec[1])
        if fp is not None:
            fp["key"] = f"0x{key[0]:04x}/0x{key[1]:04x}"
            lsc_records.append(fp)
    if lsc_records:
        summary["lsc"] = lsc_records

    return summary


def build_compare_report(paths: list[Path]) -> list[dict[str, Any]]:
    return [build_compare_summary(path, variant=0) for path in paths]


def dump_compare(summaries: list[dict[str, Any]]) -> None:
    for idx, summary in enumerate(summaries):
        if idx:
            print()
        path = Path(summary["path"])
        print(f"{path.name}: sensor={summary['sensor']} variant={summary['variant']}")
        print(f"  records_offset=0x{summary['records_offset']:x} record_count={summary['record_count']}")
        sensor_info = summary.get("sensor_info")
        if sensor_info is not None:
            print(
                "  sensor_info="
                f"{sensor_info['width']}x{sensor_info['height']} "
                f"fmt={sensor_info['format_code']} lanes={sensor_info['mipi_lanes']} "
                f"bpp={sensor_info['bits_per_pixel']}"
            )
        awb = summary.get("r01_awb")
        if awb is not None:
            print(
                "  r01_awb="
                f"entries={awb['entry_count']} illum={awb['illuminant_codes']} "
                f"gain0_first3={awb['gain0_first3']}"
            )
        chroma = summary.get("r07_chromaticity")
        if chroma is not None:
            print(
                "  r07="
                f"{chroma['key']} quads={chroma['quad_count']} "
                f"anchors={chroma['anchor_point_count']} "
                f"tail={chroma['tail_quad_count']} "
                f"anchor_xy_first3={chroma['anchor_xy_first3']}"
            )
        gains = summary.get("r10_default_gains")
        if gains is not None:
            print(
                "  r10="
                f"u16={gains['u16']} gain_x256={gains['gain_x256']}"
            )
        lsc = summary.get("lsc")
        if lsc is not None:
            for fp in lsc:
                print(
                    "  lsc="
                    f"{fp['key']} len={fp['payload_len']} "
                    f"dims={fp['dims_u16']} first_gain={fp['first_gain_f32']}"
                )
        matrix = summary.get("r11_matrix_bank")
        if matrix is not None:
            print(
                "  r11="
                f"layout={matrix['layout']} header={matrix['header_size']} "
                f"banks={matrix['bank_count']} matrices={matrix['matrix_count_per_bank']} "
                f"axis_first5={matrix['axis_first5']} axis_last3={matrix['axis_last3']}"
            )
            print(f"    bank0_header={matrix['bank0_header']}")
            print(f"    bank0_matrix0={matrix['bank0_matrix0']}")
            print(f"    bank0_matrix_last={matrix['bank0_matrix_last']}")
            for bank in matrix["bank_stats"][:2]:
                print(
                    "    bank_stats="
                    f"bank={bank['bank']} "
                    f"coeff=[{bank['coeff_min']}, {bank['coeff_max']}] "
                    f"m0_trace={bank['matrix0_trace']} "
                    f"m0_det={bank['matrix0_det']} "
                    f"last_trace={bank['matrix_last_trace']} "
                    f"last_det={bank['matrix_last_det']} "
                    f"last_tail_zero={bank['matrix_last_tail_zero']}"
                )


def decode_u16_pair_table(body: bytes, header_words: int = 2) -> dict[str, Any] | None:
    if len(body) < header_words * 2 or len(body) % 2 != 0:
        return None
    vals = struct.unpack_from("<" + "H" * (len(body) // 2), body)
    if len(vals) < header_words:
        return None
    rest = vals[header_words:]
    if len(rest) % 2 != 0:
        return None
    return {
        "header_u16": list(vals[:header_words]),
        "pairs": [[rest[i], rest[i + 1]] for i in range(0, len(rest), 2)],
    }


def decode_u16_scalar_tuple(body: bytes) -> dict[str, Any] | None:
    if len(body) == 0 or len(body) % 2 != 0:
        return None
    vals = list(struct.unpack_from("<" + "H" * (len(body) // 2), body))
    return {
        "u16": vals,
        "nonzero_u16": [v for v in vals if v != 0],
    }


def decode_two_u32_header(body: bytes) -> dict[str, Any] | None:
    if len(body) != 24:
        return None
    vals = struct.unpack_from("<6I", body, 0)
    return {
        "u32": list(vals),
        "header": list(vals[:2]),
        "tail_zero": list(vals[2:]),
    }


def decode_record(rtype: int, flags: int, body: bytes) -> dict[str, Any] | None:
    """Dispatch to a type-specific decoder. Returns None if the
    combination is not decoded yet."""
    if rtype == 0x0066 and flags == 0x0002:
        return decode_sensor_info(body)
    if rtype == 0x0064 and flags == 0x0003:
        return decode_awb_illuminants(body)
    if rtype == 0x0065 and flags == 0x0007:
        return decode_single_u32(body, field="value_u32")
    if rtype == 0x0065 and flags == 0x0011:
        return decode_single_u32(body, field="value_u32")
    if rtype == 0x0064 and flags == 0x0013:
        return decode_single_u32(body, field="value_u32")
    if rtype == 0x0066 and flags == 0x000f:
        return decode_chromaticity_quad_table(body)
    if rtype == 0x0066 and flags == 0x0014:
        return decode_default_gains(body)
    if rtype == 0x0065 and flags == 0x0019:
        return decode_matrix_bank_table(body)
    if rtype == 0x0065 and flags == 0x001a:
        return decode_constant_f32_table(body)
    if rtype == 0x00c8 and flags == 0x0009:
        return decode_six_f32(body)
    if rtype == 0x0064 and flags == 0x0024:
        return decode_u16_tuple(body)
    if rtype == 0x0064 and flags == 0x0025:
        return decode_single_u32(body, field="value_u32")
    if rtype == 0x0067 and flags == 0x0106:
        return decode_u16_pair_table(body)
    if rtype == 0x0064 and flags == 0x0107:
        return decode_u16_pair_table(body)
    if rtype == 0x0064 and flags == 0x0109:
        return decode_u16_scalar_tuple(body)
    if rtype == 0x0064 and flags == 0x0110:
        return decode_two_u32_header(body)
    if rtype == 0x0064 and flags == 0x0111:
        return decode_single_u32(body, field="value_u32")
    return None


def dump_record_views(body: bytes, max_lines: int = 8) -> list[str]:
    """Produce several human-readable interpretations of a record body.
    Intended for RE: run this on an unknown record and eyeball which
    interpretation looks like a real table."""
    lines: list[str] = []
    lines.append(f"length: {len(body)} bytes")
    # Hex dump, first few lines only
    for i in range(0, min(len(body), max_lines * 16), 16):
        chunk = body[i:i + 16]
        ascii_part = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        lines.append(f"  {i:04x}: {chunk.hex(' ', 2):<47s}  |{ascii_part}|")
    if len(body) > max_lines * 16:
        lines.append(f"  ... {len(body) - max_lines * 16} more bytes")

    # Try a few interpretations of the first 32 bytes
    head = body[:32]
    if len(head) >= 4:
        lines.append("  u32 LE (first 8):  " + " ".join(
            f"{v}" for v in struct.unpack_from(
                "<" + "I" * min(8, len(head) // 4), head)))
        lines.append("  u16 LE (first 16): " + " ".join(
            f"{v}" for v in struct.unpack_from(
                "<" + "H" * min(16, len(head) // 2), head)))
        if len(head) >= 32:
            lines.append("  f32 LE (first 8):  " + " ".join(
                f"{v:.4g}" for v in struct.unpack_from("<8f", head)))
    return lines


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
    aiqbs = get_aiqb_variants(root)
    for i, c in enumerate(aiqbs):
        print()
        print(f"aiqb[{i}] payload metadata:")
        payload, meta, records = get_aiqb_records(buf, c)
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

        covered = sum(r.length for r in records)
        tail = c.payload_size - (meta["records_offset"] + covered)
        print(f"  records ({len(records)}, covers "
              f"0x{covered:x}/0x{c.payload_size - meta['records_offset']:x} "
              f"of record stream, tail=0x{tail:x}):")
        for idx, r in enumerate(records[:40]):
            body = payload[r.offset + 8:r.offset + r.length]
            decoded = decode_record(r.record_type, r.flags, body)
            decoded_suffix = f"  decoded={decoded}" if decoded else ""
            print(f"    [{idx:2d}] @0x{r.offset:06x}  type=0x{r.record_type:04x} "
                  f"flags=0x{r.flags:04x}  len=0x{r.length:06x}  "
                  f"preview={r.payload_preview_hex}{decoded_suffix}")
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
    for c in get_aiqb_variants(root):
        payload, meta, records = get_aiqb_records(buf, c)
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
                    "decoded": decode_record(
                        r.record_type,
                        r.flags,
                        payload[r.offset + 8:r.offset + r.length],
                    ),
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


def _select_aiqb_record(root: Container, buf: bytes,
                        variant: int, index: int
                        ) -> tuple[Record, bytes] | None:
    aiqbs = get_aiqb_variants(root)
    if variant < 0 or variant >= len(aiqbs):
        return None
    c = aiqbs[variant]
    payload, _meta, records = get_aiqb_records(buf, c)
    if index < 0 or index >= len(records):
        return None
    r = records[index]
    body = payload[r.offset + 8:r.offset + r.length]
    return r, body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, nargs="?",
                    help="AIQB / CPFF file to parse")
    ap.add_argument("--compare", type=Path, nargs="+", metavar="PATH",
                    help="compare the main AIQB variant across multiple CPFF / AIQB files")
    ap.add_argument("--compare-json", type=Path,
                    help="write machine-readable JSON for --compare to this path")
    ap.add_argument("--json", type=Path,
                    help="write machine-readable JSON to this path")
    ap.add_argument("--dump-record", type=str, metavar="V:N",
                    help="dump a raw record in multiple interpretations "
                         "(V = aiqb variant index, N = record index)")
    ap.add_argument("--extract-record", type=str, metavar="V:N:FILE",
                    help="write a record's raw payload to FILE")
    args = ap.parse_args()

    if args.compare:
        report = build_compare_report(args.compare)
        dump_compare(report)
        if args.compare_json is not None:
            args.compare_json.write_text(json.dumps(report, indent=2))
            print(f"\nwrote {args.compare_json}")
        return 0

    if args.path is None:
        ap.error("path is required unless --compare is used")

    buf = args.path.read_bytes()
    root = parse_container(buf, 0, len(buf))
    if root is None or root.tag != "CPFF":
        print(f"{args.path}: not a CPFF container "
              f"(first 4 bytes: {buf[:4]!r})", file=sys.stderr)
        return 1

    if args.dump_record:
        v, n = (int(x, 0) for x in args.dump_record.split(":"))
        sel = _select_aiqb_record(root, buf, v, n)
        if sel is None:
            print(f"no such record {v}:{n}", file=sys.stderr)
            return 1
        r, body = sel
        print(f"aiqb[{v}] record[{n}]: type=0x{r.record_type:04x} "
              f"flags=0x{r.flags:04x} len=0x{r.length:06x}")
        decoded = decode_record(r.record_type, r.flags, body)
        if decoded is not None:
            print(f"decoded: {json.dumps(decoded, indent=2)}")
        for line in dump_record_views(body):
            print(line)
        return 0

    if args.extract_record:
        v, n, out = args.extract_record.split(":", 2)
        sel = _select_aiqb_record(root, buf, int(v, 0), int(n, 0))
        if sel is None:
            print(f"no such record {v}:{n}", file=sys.stderr)
            return 1
        _, body = sel
        Path(out).write_bytes(body)
        print(f"wrote {len(body)} bytes to {out}")
        return 0

    dump_text(args.path, root, buf)

    if args.json is not None:
        data = dump_json(args.path, root, buf)
        args.json.write_text(json.dumps(data, indent=2))
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
