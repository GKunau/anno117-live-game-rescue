"""Compression wrapper of the files inside an ``.a8s`` container (``meta.a7s``, ``data.a7s`` ...).

Layout::

    [zlib stream][empty zlib stream 78 da 03 00 00 00 00 01][u32 decompressed size]

Any valid zlib stream decodes the same way, so re-encoded files do not have to be
byte-identical to what the game wrote.
"""
from __future__ import annotations

import struct
import zlib

TERMINATOR = bytes.fromhex("78da030000000001")


class A7SError(ValueError):
    pass


def decode(blob: bytes) -> bytes:
    d = zlib.decompressobj()
    try:
        raw = d.decompress(blob) + d.flush()
    except zlib.error as exc:
        raise A7SError("zlib: %s" % exc) from exc
    rest = d.unused_data
    if len(rest) != 12 or rest[:8] != TERMINATOR:
        raise A7SError("unexpected trailer after zlib stream")
    if struct.unpack("<I", rest[8:])[0] != len(raw):
        raise A7SError("size field does not match decompressed size")
    return raw


def encode(raw: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, 15, 9)
    return c.compress(raw) + c.flush() + TERMINATOR + struct.pack("<I", len(raw))
