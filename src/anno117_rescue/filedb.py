"""Minimal reader/patcher for Anno's FileDB V3 documents (the payload of every ``.a7s`` file).

Layout::

    content : sequence of nodes
              tag open   : u32 0,    u32 id (< 0x8000)
              tag close  : u32 0,    u32 0
              attribute  : u32 size, u32 id (>= 0x8000), value padded to 8 bytes
    names   : tag table and attribute table, each
              u32 count, u16 ids[count], NUL-terminated names, padded to 8 bytes
    trailer : u32 tag_table_offset, u32 attr_table_offset, 08 00 00 00 FD FF FF FF

Unnamed ids are reported as ``#<id>`` (``#1`` is the anonymous list item tag,
``#8000`` the anonymous list value attribute).

Edits are done by splicing bytes in place and shifting the two table offsets;
there are no other internal offsets in the format.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"\x08\x00\x00\x00\xfd\xff\xff\xff"


class FileDBError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    path: str
    kind: str          # "tag" or "attr"
    start: int         # offset of the node header
    end: int           # exclusive; for tags includes children and the close marker
    size: int          # attribute value size (0 for tags)
    depth: int

    def value(self, doc: bytes) -> bytes:
        return doc[self.start + 8: self.start + 8 + self.size]


def _names(doc: bytes, off: int) -> dict[int, str]:
    count = struct.unpack_from("<I", doc, off)[0]
    pos = off + 4
    ids = struct.unpack_from("<%dH" % count, doc, pos)
    pos += 2 * count
    names = []
    for _ in range(count):
        end = doc.index(b"\0", pos)
        names.append(doc[pos:end].decode("utf-8", "replace"))
        pos = end + 1
    return dict(zip(ids, names))


def _offsets(doc: bytes) -> tuple[int, int]:
    if len(doc) < 16 or doc[-8:] != MAGIC:
        raise FileDBError("not a FileDB V3 document")
    return struct.unpack_from("<II", doc, len(doc) - 16)


def scan(doc: bytes) -> list[Node]:
    """All nodes in document order (by start offset)."""
    tag_off, attr_off = _offsets(doc)
    tags, attrs = _names(doc, tag_off), _names(doc, attr_off)
    nodes: list[Node] = []
    stack: list[tuple[str, int]] = []
    pos = 0
    while pos < tag_off:
        size, ident = struct.unpack_from("<II", doc, pos)
        start = pos
        pos += 8
        if ident == 0:
            if not stack:
                break
            path, s = stack.pop()
            nodes.append(Node(path, "tag", s, pos, 0, len(stack)))
            continue
        parent = stack[-1][0] if stack else ""
        if ident < 0x8000:
            stack.append((parent + "/" + tags.get(ident, "#%d" % ident), start))
        else:
            pos += (size + 7) // 8 * 8
            if pos > tag_off:
                raise FileDBError("attribute runs past content at %#x" % start)
            nodes.append(Node(parent + "/" + attrs.get(ident, "#%x" % ident), "attr",
                              start, pos, size, len(stack)))
    if stack:
        raise FileDBError("unclosed tag %s" % stack[-1][0])
    nodes.sort(key=lambda n: n.start)
    return nodes


def find(doc: bytes, path: str, kind: str | None = None) -> list[Node]:
    return [n for n in scan(doc) if n.path == path and (kind is None or n.kind == kind)]


def values(doc: bytes, path: str) -> list[bytes]:
    return [n.value(doc) for n in find(doc, path, "attr")]


def splice(doc: bytes, start: int, end: int, new: bytes) -> bytes:
    """Replace ``doc[start:end]`` (whole nodes) by ``new`` and fix the table offsets."""
    if (end - start) % 8 or len(new) % 8:
        raise FileDBError("splice must keep 8-byte alignment")
    tag_off, attr_off = _offsets(doc)
    if end > tag_off:
        raise FileDBError("splice outside content area")
    delta = len(new) - (end - start)
    out = bytearray(doc[:start] + new + doc[end:])
    struct.pack_into("<II", out, len(out) - 16, tag_off + delta, attr_off + delta)
    return bytes(out)


def _one(doc: bytes, path: str, kind: str) -> Node:
    hits = find(doc, path, kind)
    if len(hits) != 1:
        raise FileDBError("%s: expected exactly one %s, found %d" % (path, kind, len(hits)))
    return hits[0]


def set_value(doc: bytes, path: str, value: bytes) -> bytes:
    node = _one(doc, path, "attr")
    ident = struct.unpack_from("<I", doc, node.start + 4)[0]
    new = struct.pack("<II", len(value), ident) + value + b"\0" * (-len(value) % 8)
    return splice(doc, node.start, node.end, new)


def remove(doc: bytes, path: str, kind: str) -> bytes:
    node = _one(doc, path, kind)
    return splice(doc, node.start, node.end, b"")


# ------------------------------------------------------------------ builder (used by tests)
def build(tree: list) -> bytes:
    """Build a document from ``[("tag", name, children) | ("attr", name, bytes), ...]``."""
    tag_ids: dict[str, int] = {}
    attr_ids: dict[str, int] = {}

    def tid(name: str) -> int:
        if name.startswith("#"):
            return int(name[1:])
        return tag_ids.setdefault(name, len(tag_ids) + 2)

    def aid(name: str) -> int:
        if name.startswith("#"):
            return int(name[1:], 16)
        return attr_ids.setdefault(name, 0x8001 + len(attr_ids))

    out = bytearray()

    def emit(items):
        for item in items:
            if item[0] == "tag":
                out.extend(struct.pack("<II", 0, tid(item[1])))
                emit(item[2])
                out.extend(struct.pack("<II", 0, 0))
            else:
                v = item[2]
                out.extend(struct.pack("<II", len(v), aid(item[1])) + v + b"\0" * (-len(v) % 8))

    emit(tree)
    out.extend(struct.pack("<II", 0, 0))

    def table(names: dict[str, int]) -> bytes:
        t = struct.pack("<I", len(names)) + b"".join(struct.pack("<H", i) for i in names.values())
        t += b"".join(n.encode() + b"\0" for n in names)
        return t + b"\0" * (-len(t) % 8)

    tag_off = len(out)
    out.extend(table(tag_ids))
    attr_off = len(out)
    out.extend(table(attr_ids))
    out.extend(struct.pack("<II", tag_off, attr_off) + MAGIC)
    return bytes(out)


# ------------------------------------------------------------------ text dump
def _fmt(v: bytes) -> str:
    if not v:
        return "<empty>"
    body = v[:-2] if v.endswith(b"\0\0") else v
    if len(v) > 4 and len(v) % 2 == 0 and body and all(body[i + 1] == 0 and 32 <= body[i] < 127
                                                        for i in range(0, len(body) - 1, 2)):
        return 'utf16 "%s"' % v.decode("utf-16le").rstrip("\0")
    s = v.rstrip(b"\0")
    if len(s) >= 3 and all(32 <= c < 127 for c in s):
        return '"%s"' % s.decode()
    if len(v) in (1, 2, 4, 8):
        fmt = {1: "<B", 2: "<H", 4: "<i", 8: "<q"}[len(v)]
        return str(struct.unpack(fmt, v)[0])
    h = v.hex()
    return "hex[%d] %s%s" % (len(v), h[:96], "..." if len(h) > 96 else "")


def dump(doc: bytes) -> str:
    lines = []
    for n in scan(doc):
        name = n.path.rsplit("/", 1)[1]
        if n.kind == "tag":
            lines.append("  " * n.depth + "<%s>" % name)
        else:
            lines.append("  " * n.depth + "%s = %s" % (name, _fmt(n.value(doc))))
    return "\n".join(lines) + "\n"
