import contextlib
import io
import os
import tempfile
import unittest
import uuid

from anno117_rescue import cli, filedb
from anno117_rescue.savegame import SaveError, SaveGame

from fixtures import COOP_ID, FRIEND, HOST, build_save


class InfoTest(unittest.TestCase):
    def test_summary(self):
        info = SaveGame(build_save()).info()
        self.assertEqual(info["name"], "QuickSave")
        self.assertEqual(info["simulation_steps"], 86128)
        self.assertEqual(info["population"], 46663)
        self.assertEqual(info["money"], 472492)
        self.assertEqual(info["game_seed"], 9885)
        self.assertEqual(info["corporation_id"], 1793989391)
        self.assertEqual(info["coop_id"], COOP_ID)
        self.assertEqual(info["coop_creator"], HOST)
        self.assertTrue(info["was_ever_multiplayer"])

    def test_players(self):
        slots = SaveGame(build_save()).slots()
        self.assertEqual(slots[0].company, "Marcus")
        self.assertEqual([(p.peer_id, p.account, p.active) for p in slots[0].peers],
                         [(0, HOST, True), (172, FRIEND, False)])
        self.assertEqual(slots[1].peers, [])


class RecoverTest(unittest.TestCase):
    def setUp(self):
        self.save = SaveGame(build_save())

    def test_new_id(self):
        blob, report = self.save.recover("new-id", save_name="Rescued")
        new = SaveGame(blob)
        info = new.info()
        self.assertNotEqual(info["coop_id"], COOP_ID)
        uuid.UUID(info["coop_id"])
        self.assertEqual(info["coop_creator"], HOST)
        self.assertEqual(info["name"], "Rescued")
        self.assertEqual(new.entry("data.a7s").data, self.save.entry("data.a7s").data)
        self.assertEqual(new.slots(), self.save.slots())
        self.assertEqual(report["old_coop_id"], COOP_ID)
        hd = new.raw("header.a7s")
        self.assertEqual(filedb.values(hd, "/CorporationProfile/MultiplayerCoopID"),
                         [info["coop_id"].encode()])

    def test_fixed_id(self):
        fixed = str(uuid.uuid4())
        blob, _ = self.save.recover("new-id", coop_id=fixed)
        self.assertEqual(SaveGame(blob).info()["coop_id"], fixed)

    def test_remove_id(self):
        blob, report = self.save.recover("remove-id")
        info = SaveGame(blob).info()
        self.assertIsNone(info["coop_id"])
        self.assertIsNone(info["coop_creator"])
        self.assertIsNone(report["new_coop_id"])
        self.assertEqual(info["name"], "QuickSave")

    def test_rejects_bad_uuid(self):
        with self.assertRaises(SaveError):
            self.save.recover("new-id", coop_id="not-a-uuid")

    def test_rejects_save_without_coop_id(self):
        with self.assertRaises(SaveError):
            SaveGame(build_save(with_coop=False)).recover("new-id")

    def test_deterministic(self):
        fixed = str(uuid.uuid4())
        a, _ = self.save.recover("new-id", coop_id=fixed, save_name="X")
        b, _ = self.save.recover("new-id", coop_id=fixed, save_name="X")
        self.assertEqual(a, b)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "QuickSave.a8s")
        with open(self.src, "wb") as fh:
            fh.write(build_save())

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_info(self):
        code, out, _ = self.run_cli("info", self.src)
        self.assertEqual(code, 0)
        self.assertIn("86128", out)
        self.assertIn("Marcus", out)

    def test_recover_default_output_and_no_overwrite(self):
        code, out, _ = self.run_cli("recover", self.src)
        self.assertEqual(code, 0)
        target = os.path.join(self.tmp.name, "QuickSave_Recovered.a8s")
        self.assertTrue(os.path.exists(target))
        self.assertEqual(SaveGame.load(target).info()["name"], "QuickSave_Recovered")
        before = read(target)
        code, _, err = self.run_cli("recover", self.src)
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", err)
        self.assertEqual(read(target), before)

    def test_input_never_modified(self):
        original = read(self.src)
        self.run_cli("recover", self.src, "--mode", "remove-id")
        code, _, _ = self.run_cli("recover", self.src, "-o", self.src)
        self.assertEqual(code, 2)
        self.assertEqual(read(self.src), original)

    def test_extract_and_dump(self):
        out_dir = os.path.join(self.tmp.name, "x")
        code, _, _ = self.run_cli("extract", self.src, out_dir, "--decode")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(out_dir)), ["data.bin", "gamesetup.bin", "header.bin", "meta.bin"])
        code, out, _ = self.run_cli("dump", self.src, "gamesetup")
        self.assertIn("MultiplayerCoopID", out)

    def test_bad_file(self):
        bad = os.path.join(self.tmp.name, "bad.a8s")
        with open(bad, "wb") as fh:
            fh.write(b"nope")
        code, _, err = self.run_cli("info", bad)
        self.assertEqual(code, 1)
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
