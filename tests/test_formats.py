import struct
import unittest

from anno117_rescue import a7s, filedb, rda

from fixtures import build_save


class RDATest(unittest.TestCase):
    def test_roundtrip_is_byte_identical(self):
        blob = build_save()
        self.assertEqual(rda.write(rda.read(blob)), blob)

    def test_entries(self):
        names = [e.name for e in rda.read(build_save())]
        self.assertEqual(names, ["meta.a7s", "header.a7s", "gamesetup.a7s", "data.a7s"])

    def test_block_chain_layout(self):
        blob = rda.write([rda.Entry("a.a7s", b"x" * 10), rda.Entry("b.a7s", b"y" * 3)])
        first = struct.unpack_from("<Q", blob, 784)[0]
        self.assertEqual(first, 792 + 10 + 560)
        nxt = struct.unpack_from("<IIQQQ", blob, first)[4]
        self.assertEqual(nxt, first + 32 + 3 + 560)
        self.assertEqual(struct.unpack_from("<IIQQQ", blob, nxt)[4], len(blob))

    def test_rejects_wrong_magic(self):
        with self.assertRaises(rda.RDAError):
            rda.read(b"Resource File V2.0" + b"\0" * 800)

    def test_rejects_truncated(self):
        with self.assertRaises(rda.RDAError):
            rda.read(build_save()[:-10])


class A7STest(unittest.TestCase):
    def test_roundtrip(self):
        raw = b"hello anno" * 1000
        self.assertEqual(a7s.decode(a7s.encode(raw)), raw)

    def test_trailer(self):
        enc = a7s.encode(b"abc")
        self.assertEqual(enc[-12:-4], a7s.TERMINATOR)
        self.assertEqual(struct.unpack("<I", enc[-4:])[0], 3)

    def test_wrong_size_field(self):
        enc = bytearray(a7s.encode(b"abc"))
        enc[-4:] = struct.pack("<I", 4)
        with self.assertRaises(a7s.A7SError):
            a7s.decode(bytes(enc))


class FileDBTest(unittest.TestCase):
    def setUp(self):
        self.doc = filedb.build([("tag", "Root", [
            ("attr", "Name", b"abc"),
            ("tag", "List", [("tag", "#1", [("attr", "#8000", b"\x01\x00\x00\x00")])]),
            ("attr", "After", b"z"),
        ])])

    def test_scan_paths(self):
        paths = [n.path for n in filedb.scan(self.doc)]
        self.assertEqual(paths, ["/Root", "/Root/Name", "/Root/List", "/Root/List/#1",
                                 "/Root/List/#1/#8000", "/Root/After"])

    def test_values(self):
        self.assertEqual(filedb.values(self.doc, "/Root/Name"), [b"abc"])

    def test_set_value_with_new_length(self):
        doc = filedb.set_value(self.doc, "/Root/Name", b"a much longer value")
        self.assertEqual(filedb.values(doc, "/Root/Name"), [b"a much longer value"])
        self.assertEqual(filedb.values(doc, "/Root/After"), [b"z"])

    def test_remove(self):
        doc = filedb.remove(self.doc, "/Root/List", "tag")
        self.assertEqual([n.path for n in filedb.scan(doc)], ["/Root", "/Root/Name", "/Root/After"])

    def test_splice_alignment(self):
        with self.assertRaises(filedb.FileDBError):
            filedb.splice(self.doc, 0, 8, b"abc")

    def test_ambiguous_path(self):
        doc = filedb.build([("attr", "X", b"1"), ("attr", "X", b"2")])
        with self.assertRaises(filedb.FileDBError):
            filedb.set_value(doc, "/X", b"3")

    def test_dump(self):
        text = filedb.dump(self.doc)
        self.assertIn('Name = "abc"', text)
        self.assertIn("<List>", text)


if __name__ == "__main__":
    unittest.main()
