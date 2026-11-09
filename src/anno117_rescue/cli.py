"""Command line interface: ``anno117-rescue {info,recover,extract,dump}``."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys

from . import __version__, a7s, filedb
from .savegame import SaveGame


def _short(account: str | None) -> str:
    return (account or "?")[:8] + "…"


def cmd_info(args) -> int:
    rows = []
    for path in args.saves:
        info = SaveGame.load(path).info()
        info["file"] = os.path.basename(path)
        rows.append(info)
    if args.json:
        print(json.dumps(rows, indent=2, default=lambda o: dataclasses.asdict(o)))
        return 0
    fields = [
        ("file", "File"), ("name", "Save name"), ("saved", "Saved"), ("created", "Game created"),
        ("simulation_steps", "Simulation steps"), ("population", "Population"), ("money", "Money"),
        ("playtime_hours", "Playtime (h)"), ("world_size_mb", "World data (MB)"),
        ("game_seed", "Game seed"), ("corporation_id", "Corporation ID"),
        ("was_ever_multiplayer", "Ever multiplayer"), ("coop_id", "Live/co-op ID"),
    ]
    cell = lambda r, k: "-" if r.get(k) is None else str(r[k])
    width = max(len(label) for _, label in fields)
    cols = [max(len(cell(r, k)) for k, _ in fields) for r in rows]
    for key, label in fields:
        print(label.ljust(width), "  ".join(cell(r, key).ljust(w) for r, w in zip(rows, cols)).rstrip())
    for r in rows:
        print("\nPlayers in %s:" % r["file"])
        for s in r["slots"]:
            if not s.company and not s.peers:
                continue
            peers = ", ".join("peer %d %s (%s)" % (p.peer_id, _short(p.account), "active" if p.active else "absent")
                              for p in s.peers) or "AI / no players"
            print("  slot %d %-12s %s" % (s.slot_id, s.company or "", peers))
    return 0


def cmd_recover(args) -> int:
    src = os.path.abspath(args.save)
    out = args.output or os.path.splitext(args.save)[0] + "_Recovered.a8s"
    if os.path.abspath(out) == src:
        print("error: output must differ from input", file=sys.stderr)
        return 2
    if os.path.exists(out):
        print("error: %s already exists – refusing to overwrite" % out, file=sys.stderr)
        return 2
    save = SaveGame.load(args.save)
    name = None if args.keep_name else (args.name or os.path.splitext(os.path.basename(out))[0])
    blob, report = save.recover(args.mode, args.coop_id, name)
    with open(out, "xb") as fh:
        fh.write(blob)
    print("input : %s (sha256 %s)" % (args.save, hashlib.sha256(save.blob).hexdigest()[:16]))
    print("output: %s (sha256 %s, %d bytes)" % (out, hashlib.sha256(blob).hexdigest()[:16], len(blob)))
    print("old live/co-op ID: %s" % report["old_coop_id"])
    print("new live/co-op ID: %s" % (report["new_coop_id"] or "(removed)"))
    print("save name        : %s" % report["name"])
    for f, paths in report["changed"].items():
        print("  %-14s changed: %s" % (f, ", ".join(paths) or "nothing"))
    print("  data.a7s       unchanged (world copied byte for byte)")
    print("\nStructure verified. Back up your save folder before trying the file in game.")
    return 0


def cmd_extract(args) -> int:
    save = SaveGame.load(args.save)
    os.makedirs(args.directory, exist_ok=True)
    for e in save.entries:
        target = os.path.join(args.directory, e.name if not args.decode else e.name.replace(".a7s", ".bin"))
        if os.path.exists(target):
            print("skip (exists): %s" % target)
            continue
        with open(target, "xb") as fh:
            fh.write(a7s.decode(e.data) if args.decode else e.data)
        print("wrote %s" % target)
    return 0


def cmd_dump(args) -> int:
    save = SaveGame.load(args.save)
    member = args.member if args.member.endswith(".a7s") else args.member + ".a7s"
    sys.stdout.write(filedb.dump(save.raw(member)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="anno117-rescue",
                                 description="Inspect and rescue Anno 117 co-op/live save games (.a8s).")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="compare key facts of one or more saves")
    p.add_argument("saves", nargs="+")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("recover", help="write a copy detached from its live/co-op save link")
    p.add_argument("save")
    p.add_argument("-o", "--output", help="output file (default: <input>_Recovered.a8s)")
    p.add_argument("--mode", choices=["new-id", "remove-id"], default="new-id",
                   help="new-id: assign a new random live/co-op ID (default); "
                        "remove-id: remove the ID and the co-op group creator")
    p.add_argument("--coop-id", help="use this UUID instead of a random one (mode new-id)")
    p.add_argument("--name", help="display name stored in the save (default: output file name)")
    p.add_argument("--keep-name", action="store_true", help="keep the original display name")
    p.set_defaults(func=cmd_recover)

    p = sub.add_parser("extract", help="extract the inner files (meta, header, gamesetup, data)")
    p.add_argument("save")
    p.add_argument("directory")
    p.add_argument("--decode", action="store_true", help="write decompressed FileDB documents (.bin)")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("dump", help="print an inner file as a readable tree")
    p.add_argument("save")
    p.add_argument("member", nargs="?", default="gamesetup",
                   help="meta, header, gamesetup or data (default: gamesetup)")
    p.set_defaults(func=cmd_dump)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
