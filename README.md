# anno117-live-game-rescue

Inspect and rescue **Anno 117: Pax Romana** co-op / live save games (`.a8s`).

Built after a co-op game with *live savegame* enabled got its whole world reset:
loading an older manual save replaced the world with a freshly generated one, and from
then on **every** older save of that game loaded the reset world again – even with cloud
sync turned off. The older save files were still intact on disk; the game just never
showed them.

This tool lets you

- **compare** saves side by side (save time, simulation steps, population, money,
  players, live/co-op ID) to find the last intact one, and
- **recover** an intact save by writing a copy that is no longer tied to the broken
  live game, so the game loads the world that is actually in the file.

Pure Python 3.9+, no dependencies. The input file is only read, never modified, and
existing files are never overwritten.

> Not affiliated with or endorsed by Ubisoft. Use at your own risk and **back up your
> save folder first**.

## Quick start

```sh
git clone https://github.com/<you>/anno117-live-game-rescue.git
cd anno117-live-game-rescue
python -m pip install .          # optional, provides the `anno117-rescue` command
```

Without installing, run it from the repository folder with
`PYTHONPATH=src python -m anno117_rescue ...` (Windows PowerShell:
`$env:PYTHONPATH="src"; python -m anno117_rescue ...`).

Copy the save files you want to work with from your Anno 117 save folder into a
separate folder first.

### 1. Find the last intact save

```text
$ anno117-rescue info QuickSave.a8s "Autosave 133.a8s"
File             QuickSave.a8s                         Autosave 133.a8s
Save name        QuickSave                             Autosave
Saved            2026-11-08 16:25                      2026-11-08 19:05
Game created     2026-11-06 19:02                      2026-11-06 19:02
Simulation steps 86128                                 319
Population       46663                                 2246
Money            472492                                761815
Playtime (h)     22.2                                  22.7
World data (MB)  57.1                                  63.5
Game seed        9885                                  9885
Corporation ID   1793989391                            1793989391
Ever multiplayer True                                  True
Live/co-op ID    3f2a9c1e-7b4d-4e8a-9c21-5d6e7f8a9b0c  3f2a9c1e-7b4d-4e8a-9c21-5d6e7f8a9b0c
```

Here the autosave is newer but has the same seed and creation time with only 319
simulation steps: it is a freshly regenerated world. The QuickSave is the one to rescue.
`--json` gives machine-readable output.

### 2. Write a recovered copy

```sh
anno117-rescue recover QuickSave.a8s
# -> QuickSave_Recovered.a8s, shown in game as "QuickSave_Recovered"
```

| Option | Effect |
|---|---|
| `--mode new-id` (default) | Gives the save a new random live/co-op ID. Everything else stays, including players and the co-op group creator. |
| `--mode remove-id` | Removes the live/co-op ID and the co-op group creator entirely. Try this if `new-id` does not help. |
| `-o FILE` | Output file name. |
| `--name NAME` / `--keep-name` | Display name shown in the load menu. |
| `--coop-id UUID` | Use a specific ID instead of a random one. |

Both modes leave the world data (`data.a7s`) byte for byte unchanged and verify the
result before writing it.

### 3. Load it and make it a live game again

1. Put the recovered file into your save folder and load it as host. It loads as a
   regular multiplayer game with the full world.
2. Enabling *live savegame* may be greyed out with *"not possible in a competitive
   multiplayer session"*, even for pure co-op games.
3. In game, remove the other players from the session, then invite them again.
4. Live savegame can now be enabled again.

This is what worked for us (game build changelist 1733841). Other builds may behave
differently.

## Other commands

```sh
anno117-rescue dump QuickSave.a8s gamesetup        # inner file as readable tree (meta|header|gamesetup|data)
anno117-rescue extract QuickSave.a8s out/ --decode # write the inner files, optionally decompressed
```

## How it works

| Layer | Format |
|---|---|
| `.a8s` | Ubisoft *Resource File V2.2* (RDA). 792-byte header, then per file: data, 560-byte directory entry, 32-byte block header. No RDA-level compression, encryption or checksums. |
| `meta.a7s`, `header.a7s`, `gamesetup.a7s`, `data.a7s` | zlib stream + empty zlib stream (`78 da 03 00 00 00 00 01`) + u32 decompressed size. |
| inner document | FileDB V3: tag/attribute nodes, name tables, trailer `08 00 00 00 FD FF FF FF`. |

What we found in the files:

- `meta.a7s` holds only version, display name and timestamp. There is no save ID.
- `data.a7s` is the world. `SavegameChecksum` and `SavegameStepcount` in the header and
  game setup belong to it, so the world must never be mixed with headers from another save.
- The live/co-op link is `MultiplayerCoopID` plus `CreatorOfPersistentCoopGroup`, stored
  in both `header.a7s` and `gamesetup.a7s`. Our assumption is that loading any save with
  this ID makes the game prefer the latest cloud state of that live group – which, after
  the reset, was the empty world. Giving the save a new ID (or none) breaks that link.

Rebuilding an unmodified save reproduces it byte for byte. Re-compressed inner files are
not byte-identical to what the game writes, but decompress to exactly the same content.

## Privacy

Save files contain Ubisoft account IDs and player names. Do not attach real saves to
public issues. `info` only prints the first 8 characters of account IDs; `dump` and
`extract` print everything.

## Development

```sh
PYTHONPATH=src:tests python -m unittest discover -s tests -v
```

The tests use small synthetic saves built in `tests/fixtures.py`, no real save files.

## Related projects

- [anno-mods](https://github.com/anno-mods) – Anno modding tools, including FileDBReader
- [AnnoSavegameViewer](https://github.com/Veraatversus/AnnoSavegameViewer)

## License

MIT
