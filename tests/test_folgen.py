import os, tempfile, unittest
from ohrwurm.sammlung import Sammlung


def album(id, name, datum):
    return {"id": id, "attributes": {"name": name, "releaseDate": datum}}


class Katalog:
    land = "de"
    def __init__(self):
        self.alben = {"full-albums": [album("a1", "Alt", "2020-01-01")], "singles": [album("s1", "Alt-Single", "2021-01-01")]}
    def kuenstler(self, kid):
        return {"id": kid, "attributes": {"name": "N4C"}}
    def ansicht(self, kid, v, frisch=False):
        return self.alben.get(v, [])


class Test(unittest.TestCase):
    def test_folgen_und_neuheiten(self):
        with tempfile.TemporaryDirectory() as t:
            s = Sammlung(os.path.join(t, "d"), [t])
            s.katalog = Katalog()
            gewuenscht = []
            s.wuenschen = lambda art, id: gewuenscht.append((art, id))
            s.folgen("824417155", automatisch=True)
            self.assertEqual(s.pruefen(), [])                                   # Bisheriges zählt nicht
            s.katalog.alben["singles"] += [album("s2", "SHADOW", "2026-06-01"), album("s3", "Bald", "2999-01-01")]
            neu = s.pruefen()
            self.assertEqual([n["name"] for n in neu], ["SHADOW"])             # Vorankündigung erst, wenn erschienen
            self.assertEqual(gewuenscht, [("album", "s2")])
            self.assertEqual(s.pruefen(), [])                                   # nicht doppelt
            self.assertEqual([n["name"] for n in s.neuheiten()], ["SHADOW"])
            s.gesehen()
            self.assertEqual(s.neuheiten(), [])
            s.entfolgen("824417155")
            self.assertEqual(s.gefolgt(), [])


if __name__ == "__main__":
    unittest.main()
