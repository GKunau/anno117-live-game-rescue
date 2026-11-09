"""Ubisoft "Resource File V2.2" (RDA) container, as used by Anno 117 ``.a8s`` saves.

Layout::

    [18 B magic "Resource File V2.2"][766 B zero padding][u64 offset of first block header]
    per file:
        [file data][directory: 560 B per entry][block header: 32 B]

    block header : u32 flags, u32 file_count, u64 dir_size, u64 dir_decompressed_size, u64 next_block
    dir entry    : 520 B UTF-16LE name, u64 offset, u64 compressed, u64 size, u64 timestamp, u64 unknown

Anno 117 saves use flags = 0 (no RDA-level compression or encryption, no checksums)
and one file per block. Only that variant is supported.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"Resource File V2.2"
HEADER_SIZE = 18 + 766 + 8
DIR_ENTRY_SIZE = 560
BLOCK_HEADER_SIZE = 32
NAME_SIZE = 520


class RDAError(ValueError):
    pass


@dataclass
class Entry:
    name: str
    data: bytes
    timestamp: int = 0
    unknown: int = 0


def read(blob: bytes) -> list[Entry]:
    if blob[:18] != MAGIC:
        raise RDAError("not a Resource File V2.2 container")
    if blob[18:784] != b"\0" * 766:
        raise RDAError("unexpected data in header padding")
    off = struct.unpack_from("<Q", blob, 784)[0]
    entries: list[Entry] = []
    seen = set()
    while off < len(blob):
        if off in seen or off + BLOCK_HEADER_SIZE > len(blob):
            raise RDAError("broken block chain at %#x" % off)
        seen.add(off)
        flags, count, dir_size, dir_dec, nxt = struct.unpack_from("<IIQQQ", blob, off)
        if flags != 0:
            raise RDAError("unsupported block flags %#x at %#x" % (flags, off))
        if dir_size != count * DIR_ENTRY_SIZE or dir_dec != dir_size:
            raise RDAError("unexpected directory size at %#x" % off)
        start = off - dir_size
        for i in range(count):
            e = blob[start + i * DIR_ENTRY_SIZE: start + (i + 1) * DIR_ENTRY_SIZE]
            name = e[:NAME_SIZE].decode("utf-16le").split("\0", 1)[0]
            fo, comp, size, ts, unk = struct.unpack_from("<QQQQQ", e, NAME_SIZE)
            if comp != size:
                raise RDAError("compressed RDA entries are not supported (%s)" % name)
            if fo + comp > start:
                raise RDAError("entry %s overlaps its directory" % name)
            entries.append(Entry(name, blob[fo:fo + comp], ts, unk))
        off = nxt
    if off != len(blob):
        raise RDAError("block chain does not end at end of file")
    return entries


def write(entries: list[Entry]) -> bytes:
    if not entries:
        raise RDAError("nothing to write")
    headers = []
    pos = HEADER_SIZE
    for e in entries:
        pos += len(e.data) + DIR_ENTRY_SIZE
        headers.append(pos)
        pos += BLOCK_HEADER_SIZE
    out = bytearray(MAGIC + b"\0" * 766)
    out += struct.pack("<Q", headers[0])
    for i, e in enumerate(entries):
        data_off = len(out)
        out += e.data
        name = e.name.encode("utf-16le")
        if len(name) > NAME_SIZE - 2:
            raise RDAError("file name too long: %s" % e.name)
        out += name + b"\0" * (NAME_SIZE - len(name))
        out += struct.pack("<QQQQQ", data_off, len(e.data), len(e.data), e.timestamp, e.unknown)
        assert len(out) == headers[i]
        nxt = headers[i + 1] if i + 1 < len(entries) else pos
        out += struct.pack("<IIQQQ", 0, 1, DIR_ENTRY_SIZE, DIR_ENTRY_SIZE, nxt)
    return bytes(out)
