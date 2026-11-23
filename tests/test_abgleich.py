import unittest
from ohrwurm import abgleich, apple


def album(id, name, datum, n=0):
    return {"id": id, "attributes": {"name": name, "releaseDate": datum, "trackCount": n}}


def lied(name, isrc, ms=200000, kuenstler="Michael Jackson"):
    return {"attributes": {"name": name, "isrc": isrc, "durationInMillis": ms, "artistName": kuenstler}}


class Test(unittest.TestCase):
    def test_einfach(self):
        self.assertEqual(abgleich.einfach("Billie Jean (2008 Remaster)"), "billiejean")
        self.assertEqual(abgleich.einfach("Beat It - Single Version"), "beatit")
        self.assertEqual(abgleich.einfach("Café feat. X"), "cafe")

    def test_jedes_lied_einmal_heimat_frueheste(self):
        thriller = album("1", "Thriller", "1982-11-30", 9)
        best = album("2", "Number Ones", "2003-11-18", 18)
        single = album("3", "Billie Jean - Single", "1983-01-02", 1)
        l = abgleich.lieder_sammeln([
            ("compilation-albums", best, [lied("Billie Jean", "A"), lied("Black or White", "B")]),
            ("singles", single, [lied("Billie Jean", "A")]),
            ("full-albums", thriller, [lied("Billie Jean", "A")]),
        ])
        self.assertEqual(len(l), 1)                  # „Black or White“ nur auf der Zusammenstellung → kein Lied
        self.assertEqual(l[0].heimat["id"], "1")
        self.assertEqual(len(l[0].auch_auf), 2)

    def test_zuordnen_und_doppelt(self):
        l = abgleich.lieder_sammeln([("full-albums", album("1", "Bad", "1987-08-31"), [lied("Bad", "X", 247000), lied("Smooth Criminal", None, 257000)])])
        rest = abgleich.zuordnen(l, [
            {"pfad": "a.mp3", "isrc": "X", "format": "mp3", "bitrate": 320000},
            {"pfad": "b.flac", "isrc": None, "titel": "Bad (Remastered)", "dauer": 248, "format": "flac", "bitrate": 900000},
            {"pfad": "c.flac", "titel": "Smooth Criminal", "dauer": 300},
            {"pfad": "d.flac", "titel": "Smooth Criminal", "dauer": 258},
        ])
        bad, sc = l
        self.assertEqual([d["pfad"] for d in bad.dateien], ["b.flac", "a.mp3"])   # FLAC zuerst
        self.assertEqual([d["pfad"] for d in sc.dateien], ["d.flac"])
        self.assertEqual([d["pfad"] for d in rest], ["c.flac"])                    # Dauer passt nicht

    def test_der_zu_roh(self):
        r, s = b"\x00" + b"\x81" * 32, b"\x01" * 31
        der = b"\x30" + bytes([4 + len(r) + len(s)]) + b"\x02" + bytes([len(r)]) + r + b"\x02" + bytes([len(s)]) + s
        roh = apple.der_zu_roh(der)
        self.assertEqual(roh, b"\x81" * 32 + b"\x00" + b"\x01" * 31)


if __name__ == "__main__":
    unittest.main()
