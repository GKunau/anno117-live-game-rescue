"""Builds small synthetic saves with the same structure as real Anno 117 saves.

No real save files are used in the tests: real saves contain Ubisoft account IDs
and player names.
"""
import struct

from anno117_rescue import a7s, filedb, rda

COOP_ID = "11111111-2222-4333-8444-555555555555"
HOST = "aaaaaaaa-0000-4000-8000-000000000001"
FRIEND = "bbbbbbbb-0000-4000-8000-000000000002"


def i32(v):
    return struct.pack("<i", v)


def i64(v):
    return struct.pack("<q", v)


def u16(v):
    return struct.pack("<H", v)


def peer(peer_id, account, active):
    body = [("tag", "ID", [("attr", "id", u16(peer_id))])]
    if active:
        body.append(("attr", "OnlineGUID", b"123456789"))
    body.append(("tag", "SavedCrossPlatformId", [("attr", "RawId", account.encode())]))
    return ("tag", "#1", [("tag", "Peer", body)])


def coop_fields(with_coop):
    if not with_coop:
        return [("attr", "WasEverMultiplayer", b"\x00")]
    return [
        ("attr", "WasEverMultiplayer", b"\x01"),
        ("attr", "MultiplayerCoopID", COOP_ID.encode()),
        ("tag", "CreatorOfPersistentCoopGroup", [("attr", "RawId", HOST.encode())]),
    ]


def slots():
    return [("tag", "SetupSlots", [
        ("tag", "Slot", [
            ("tag", "ID", [("attr", "id", u16(0))]),
            ("attr", "CompanyName", b"Marcus"),
            ("tag", "Peers", [peer(0, HOST, True), peer(172, FRIEND, False)]),
        ]),
        ("tag", "Slot", [("tag", "ID", [("attr", "id", u16(1))]), ("tag", "Peers", [])]),
    ])]


def build_save(with_coop=True, steps=86128):
    meta = filedb.build([
        ("attr", "CorporationFileVersion", i32(80)),
        ("attr", "LastModTime", i64(1794151532)),
        ("attr", "CorporationSaveGameName", "QuickSave\0".encode("utf-16le")),
    ])
    gamesetup = filedb.build([("tag", "GameSetupManager", [
        ("attr", "GameSeed", i32(9885)),
        ("attr", "SavegameStepcount", i64(steps)),
        ("attr", "SavegameChecksum", i64(-42)),
        ("attr", "CreationTimeStamp", i64(1793988164)),
        *coop_fields(with_coop),
        *slots(),
    ])])
    header = filedb.build([("tag", "CorporationProfile", [
        ("attr", "ID", i64(1793989391)),
        ("attr", "CorporationTime", i64(79929540)),
        ("attr", "SavegameStepcount", i64(steps)),
        *coop_fields(with_coop),
        *slots(),
        ("attr", "TotalPopulation", i32(46663) + b"\xff" * 16),
        ("attr", "TotalMoney", i32(472492) + b"\xff" * 16),
    ])])
    data = filedb.build([("tag", "MetaGameManager", [("attr", "World", b"islands" * 100)])])
    return rda.write([
        rda.Entry("meta.a7s", a7s.encode(meta)),
        rda.Entry("header.a7s", a7s.encode(header)),
        rda.Entry("gamesetup.a7s", a7s.encode(gamesetup)),
        rda.Entry("data.a7s", a7s.encode(data)),
    ])
