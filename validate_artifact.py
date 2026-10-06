#!/usr/bin/env python3
"""Perform lightweight structural validation of an OpenSplat scene artifact."""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"artifact validation failed: {message}")


def validate_ply(path: Path) -> dict:
    with path.open("rb") as handle:
        header = handle.read(1024 * 1024)
    if not header.startswith(b"ply\n"):
        fail("PLY header does not start with 'ply'")
    end = header.find(b"end_header\n")
    if end < 0:
        fail("PLY header has no end_header")
    header_text = header[: end + len(b"end_header\n")].decode("ascii", errors="strict")
    header_lines = header_text.splitlines()
    formats = [line.split()[1] for line in header_lines if line.startswith("format ")]
    if len(formats) != 1 or formats[0] not in {"ascii", "binary_little_endian", "binary_big_endian"}:
        fail("PLY has an unsupported or missing format declaration")
    vertices = None
    properties = []
    current_element = None
    for line in header_lines:
        fields = line.split()
        if fields[:1] == ["element"] and len(fields) == 3:
            current_element = fields[1]
        if fields[:2] == ["element", "vertex"] and len(fields) == 3:
            vertices = int(fields[2])
        elif fields[:1] == ["property"] and current_element == "vertex":
            if len(fields) == 3 and fields[1] != "list":
                properties.append(fields[1])
            else:
                fail("PLY list properties are not supported by this validator")
    if vertices is None or vertices <= 0:
        fail("PLY has no positive element vertex count")
    sizes = {"char": 1, "uchar": 1, "short": 2, "ushort": 2, "int": 4, "uint": 4, "float": 4, "double": 8}
    if not properties or any(prop not in sizes for prop in properties):
        fail("PLY has missing or unsupported vertex property types")
    payload_bytes = path.stat().st_size - (end + len(b"end_header\n"))
    if payload_bytes <= 0:
        fail("PLY has no payload")
    if formats[0] == "ascii":
        rows = header[end + len(b"end_header\n"):].splitlines()
        if len([row for row in rows if row.strip()]) < vertices:
            fail("PLY has fewer data rows than its vertex count")
    else:
        expected = vertices * sum(sizes[prop] for prop in properties)
        if payload_bytes < expected:
            fail(f"PLY payload is shorter than its declared vertex data: {payload_bytes} < {expected}")
    return {"format": "ply", "vertex_count": vertices, "property_types": properties, "header_bytes": end + len(b"end_header\n"), "payload_bytes": payload_bytes}


def validate_splat(path: Path) -> dict:
    size = path.stat().st_size
    if size < 32:
        fail("splat artifact is smaller than one 32-byte gaussian record")
    if size % 32 != 0:
        fail("splat artifact size is not a multiple of the 32-byte record size")
    with path.open("rb") as handle:
        for index in range(size // 32):
            record = handle.read(32)
            values = struct.unpack("<6f", record[:24])
            if not all(math.isfinite(value) for value in values):
                fail(f"splat record {index} contains a non-finite float")
    return {"format": "splat", "gaussian_count": size // 32, "bytes_per_gaussian": 32, "record_layout": "6 float32 + 8 uint8"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("ply", "splat"), required=True)
    parser.add_argument("--path", required=True, type=Path)
    args = parser.parse_args()
    if not args.path.is_file():
        fail(f"missing artifact: {args.path}")
    result = validate_ply(args.path) if args.format == "ply" else validate_splat(args.path)
    result["path"] = str(args.path.resolve())
    result["bytes"] = args.path.stat().st_size
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
