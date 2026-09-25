"""Just enough of the Mapbox Vector Tile format to read road lines (queue R16b).

A vector tile is protobuf: layers, each with keys, values and features; a
feature is tags (key/value index pairs), a geometry type and a geometry of
command integers (MoveTo, LineTo, ClosePath, zig-zag encoded deltas). The
library for it pins an older protobuf than OR-Tools needs, and only lines
and string or number tags are read here, so this is written out: about a
page, against the specification (github.com/mapbox/vector-tile-spec, v2).
"""

from __future__ import annotations

from typing import Any, Iterator

LINESTRING = 2


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """(field number, wire type, value): an int for varints, bytes for length-delimited, raw for fixed."""
    i, end = 0, len(buf)
    while i < end:
        key, i = _varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 2:
            size, i = _varint(buf, i)
            value, i = buf[i:i + size], i + size
        elif wire == 1:
            value, i = buf[i:i + 8], i + 8
        elif wire == 5:
            value, i = buf[i:i + 4], i + 4
        else:  # pragma: no cover -- groups are not in the format
            raise ValueError(f"wire type {wire} is not in a vector tile")
        yield number, wire, value


def _packed(buf: bytes) -> list[int]:
    out, i = [], 0
    while i < len(buf):
        value, i = _varint(buf, i)
        out.append(value)
    return out


def _value(buf: bytes) -> Any:
    import struct

    for number, _wire, raw in _fields(buf):
        if number == 1:
            return raw.decode("utf-8")
        if number == 2:
            return struct.unpack("<f", raw)[0]
        if number == 3:
            return struct.unpack("<d", raw)[0]
        if number in (4, 5):
            return raw
        if number == 6:
            return (raw >> 1) ^ -(raw & 1)
        if number == 7:
            return bool(raw)
    return None


def _lines(commands: list[int]) -> list[list[tuple[int, int]]]:
    """The command stream as lines of tile coordinates (x right, y down)."""
    lines: list[list[tuple[int, int]]] = []
    x = y = i = 0
    while i < len(commands):
        command, count = commands[i] & 7, commands[i] >> 3
        i += 1
        if command == 7:  # ClosePath: rings, not roads
            continue
        for _ in range(count):
            dx, dy = commands[i], commands[i + 1]
            i += 2
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            if command == 1:
                lines.append([(x, y)])
            elif command == 2 and lines:
                lines[-1].append((x, y))
    return [line for line in lines if len(line) > 1]


def lines(tile: bytes, layer_name: str) -> Iterator[tuple[dict[str, Any], list[list[tuple[int, int]]], int]]:
    """Each line feature of one layer: its properties, its lines in tile coordinates, and the layer's extent."""
    for number, _wire, layer in _fields(tile):
        if number != 3:
            continue
        name, keys, values, features, extent = None, [], [], [], 4096
        for field, _w, value in _fields(layer):
            if field == 1:
                name = value.decode("utf-8")
            elif field == 2:
                features.append(value)
            elif field == 3:
                keys.append(value.decode("utf-8"))
            elif field == 4:
                values.append(_value(value))
            elif field == 5:
                extent = value
        if name != layer_name:
            continue
        for feature in features:
            tags, kind, geometry = [], None, []
            for field, wire, value in _fields(feature):
                if field == 2:
                    tags = _packed(value) if wire == 2 else [value]
                elif field == 3:
                    kind = value
                elif field == 4:
                    geometry = _packed(value) if wire == 2 else [value]
            if kind != LINESTRING:
                continue
            props = {keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags) - 1, 2)}
            yield props, _lines(geometry), extent
