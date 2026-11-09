"""High-level access to an Anno 117 save: summary info and live-save recovery."""
from __future__ import annotations

import datetime as _dt
import struct
import uuid
from collections import Counter
from dataclasses import dataclass, field

from . import a7s, filedb, rda

ROOTS = {
    "gamesetup.a7s": "/GameSetupManager",
    "header.a7s": "/CorporationProfile",
}
COOP_ID = "/MultiplayerCoopID"
COOP_CREATOR = "/CreatorOfPersistentCoopGroup"
WORLD = "data.a7s"


class SaveError(ValueError):
    pass


def _int(v: bytes) -> int | None:
    if not v:
        return None
    if len(v) in (1, 2, 4, 8):
        return struct.unpack({1: "<B", 2: "<H", 4: "<i", 8: "<q"}[len(v)], v)[0]
    return struct.unpack_from("<i", v)[0]          # e.g. TotalPopulation: first i32 of a list


def _first(doc: bytes, path: str) -> bytes | None:
    vals = filedb.values(doc, path)
    return vals[0] if vals else None


def _str(v: bytes | None) -> str | None:
    return v.rstrip(b"\0").decode("utf-8", "replace") if v is not None else None


def _time(ts: int | None) -> str | None:
    if not ts:
        return None
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@dataclass
class Peer:
    peer_id: int
    account: str | None
    active: bool


@dataclass
class Slot:
    slot_id: int
    company: str | None
    peers: list[Peer] = field(default_factory=list)


class SaveGame:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.entries = rda.read(blob)
        names = [e.name for e in self.entries]
        for required in ("meta.a7s", "header.a7s", "gamesetup.a7s", WORLD):
            if required not in names:
                raise SaveError("missing %s in container (found: %s)" % (required, ", ".join(names)))
        self._raw: dict[str, bytes] = {}

    @classmethod
    def load(cls, path: str) -> "SaveGame":
        with open(path, "rb") as fh:
            return cls(fh.read())

    def entry(self, name: str) -> rda.Entry:
        return next(e for e in self.entries if e.name == name)

    def raw(self, name: str) -> bytes:
        if name not in self._raw:
            self._raw[name] = a7s.decode(self.entry(name).data)
        return self._raw[name]

    # -------------------------------------------------------------- info
    def slots(self) -> list[Slot]:
        doc = self.raw("gamesetup.a7s")
        base = ROOTS["gamesetup.a7s"] + "/SetupSlots/Slot"
        nodes = filedb.scan(doc)
        result = []
        for s in (n for n in nodes if n.path == base and n.kind == "tag"):
            inner = [n for n in nodes if s.start < n.start < s.end]
            get = lambda p: [n for n in inner if n.path == base + p]
            sid = get("/ID/id")
            comp = get("/CompanyName")
            slot = Slot(_int(sid[0].value(doc)) if sid else -1,
                        _str(comp[0].value(doc)) if comp else None)
            for p in (n for n in inner if n.path == base + "/Peers/#1/Peer" and n.kind == "tag"):
                pin = [n for n in inner if p.start < n.start < p.end]
                pget = lambda q: [n for n in pin if n.path == base + "/Peers/#1/Peer" + q]
                pid = pget("/ID/id")
                acc = pget("/SavedCrossPlatformId/RawId")
                slot.peers.append(Peer(_int(pid[0].value(doc)) if pid else -1,
                                       _str(acc[0].value(doc)) if acc else None,
                                       bool(pget("/OnlineGUID"))))
            result.append(slot)
        return result

    def info(self) -> dict:
        meta, gs, hd = self.raw("meta.a7s"), self.raw("gamesetup.a7s"), self.raw("header.a7s")
        g, h = ROOTS["gamesetup.a7s"], ROOTS["header.a7s"]
        name = _first(meta, "/CorporationSaveGameName")
        world = self.entry(WORLD).data
        return {
            "name": name.decode("utf-16le").rstrip("\0") if name else None,
            "saved": _time(_int(_first(meta, "/LastModTime") or b"")),
            "created": _time(_int(_first(gs, g + "/CreationTimeStamp") or b"")),
            "game_seed": _int(_first(gs, g + "/GameSeed") or b""),
            "simulation_steps": _int(_first(gs, g + "/SavegameStepcount") or b""),
            "population": _int(_first(hd, h + "/TotalPopulation") or b""),
            "money": _int(_first(hd, h + "/TotalMoney") or b""),
            "playtime_hours": round((_int(_first(hd, h + "/CorporationTime") or b"") or 0) / 3.6e6, 1),
            "corporation_id": _int(_first(hd, h + "/ID") or b""),
            "was_ever_multiplayer": bool(_int(_first(gs, g + "/WasEverMultiplayer") or b"")),
            "coop_id": _str(_first(gs, g + COOP_ID)),
            "coop_creator": _str(_first(gs, g + COOP_CREATOR + "/RawId")),
            "world_size_mb": round(struct.unpack("<I", world[-4:])[0] / 1e6, 1),
            "slots": self.slots(),
        }

    # -------------------------------------------------------------- recovery
    def recover(self, mode: str = "new-id", coop_id: str | None = None,
                save_name: str | None = None) -> tuple[bytes, dict]:
        """Return a new container with the live-save link replaced or removed.

        mode ``new-id``    : MultiplayerCoopID gets a new UUID (default)
        mode ``remove-id`` : MultiplayerCoopID and CreatorOfPersistentCoopGroup are removed
        The world (data.a7s) is copied byte for byte.
        """
        if mode not in ("new-id", "remove-id"):
            raise SaveError("unknown mode %r" % mode)
        if mode == "new-id":
            coop_id = coop_id or str(uuid.uuid4())
            try:
                uuid.UUID(coop_id)
            except ValueError:
                raise SaveError("not a UUID: %s" % coop_id) from None
        changed: dict[str, bytes] = {}
        old_ids = set()
        for fname, root in ROOTS.items():
            doc = self.raw(fname)
            vals = filedb.values(doc, root + COOP_ID)
            if len(vals) != 1:
                raise SaveError("%s has no single MultiplayerCoopID – is this a co-op/live save?" % fname)
            old_ids.add(_str(vals[0]))
            if mode == "new-id":
                doc = filedb.set_value(doc, root + COOP_ID, coop_id.encode())
            else:
                doc = filedb.remove(doc, root + COOP_ID, "attr")
                if filedb.find(doc, root + COOP_CREATOR, "tag"):
                    doc = filedb.remove(doc, root + COOP_CREATOR, "tag")
            changed[fname] = doc
        if save_name:
            changed["meta.a7s"] = filedb.set_value(self.raw("meta.a7s"), "/CorporationSaveGameName",
                                                   (save_name + "\0").encode("utf-16le"))
        out = [rda.Entry(e.name, a7s.encode(changed[e.name]) if e.name in changed else e.data,
                         e.timestamp, e.unknown) for e in self.entries]
        blob = rda.write(out)
        report = verify(self, blob, mode, save_name)
        report["old_coop_id"] = ", ".join(sorted(old_ids))
        return blob, report


def _signature(doc: bytes) -> Counter:
    return Counter((n.path, n.kind, n.value(doc) if n.kind == "attr" else b"") for n in filedb.scan(doc))


def verify(src: SaveGame, blob: bytes, mode: str, save_name: str | None) -> dict:
    """Re-read the result and check that exactly the intended fields changed."""
    new = SaveGame(blob)
    if [e.name for e in new.entries] != [e.name for e in src.entries]:
        raise SaveError("file list changed")
    for e in new.entries:
        if e.name != WORLD:
            filedb.scan(new.raw(e.name))
    if new.entry(WORLD).data != src.entry(WORLD).data:
        raise SaveError("world data changed")
    report = {"changed": {}}
    for fname, root in ROOTS.items():
        a, b = _signature(src.raw(fname)), _signature(new.raw(fname))
        diff = {p for p, _, _ in (a - b)} | {p for p, _, _ in (b - a)}
        allowed = {root + COOP_ID, root + COOP_CREATOR, root + COOP_CREATOR + "/RawId"}
        if diff - allowed:
            raise SaveError("unexpected changes in %s: %s" % (fname, sorted(diff - allowed)))
        report["changed"][fname] = sorted(diff)
    meta_diff = {p for p, _, _ in (_signature(src.raw("meta.a7s")) - _signature(new.raw("meta.a7s")))}
    if meta_diff - {"/CorporationSaveGameName"}:
        raise SaveError("unexpected changes in meta.a7s: %s" % sorted(meta_diff))
    report["changed"]["meta.a7s"] = sorted(meta_diff)
    report["new_coop_id"] = new.info()["coop_id"]
    report["name"] = new.info()["name"]
    return report
