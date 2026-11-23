import json, os, subprocess, tempfile, time, unittest
from ohrwurm import anschluesse, bestand
from ohrwurm.sammlung import Sammlung

INFO = {"apple_id": "1", "isrc": "USSM18700382", "titel": "Bad", "kuenstler": "Michael Jackson", "album": "Bad",
        "album_id": "9", "albumkuenstler": "Michael Jackson", "upc": None, "dauer": 3.0, "art": "album",
        "jahr": "1987", "nummer": 1, "cd": 1, "genre": "Pop", "cover": None}


def ton(pfad, **tags):
    meta = [x for k, v in tags.items() for x in ("-metadata", f"{k}={v}")]
    subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-f", "lavfi", "-i", "sine=d=3"] + meta + [pfad], check=True)


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.musik, self.eingang = os.path.join(t, "musik"), os.path.join(t, "eingang")
        os.makedirs(self.musik); os.makedirs(self.eingang)
        os.environ["ERSETZEN"] = "an"
        self.s = Sammlung(os.path.join(t, "daten"), [self.musik], eingang_ordner=self.eingang)

    def tearDown(self):
        self.tmp.cleanup()

    def wunsch(self):
        self.s.db.execute("INSERT INTO wunsch (isrc, stand, erstellt, geaendert, daten) VALUES (?,?,?,?,?)",
                          (INFO["isrc"], "offen", 0, 0, json.dumps(INFO)))
        return self.s.wuensche("offen")[0]

    def test_ablegen_taggen_doppelt_besser(self):
        w = self.wunsch()
        mp3 = os.path.join(self.eingang, "x.mp3"); ton(mp3, title="falsch")
        ziel = self.s.einsortieren(mp3, w["id"])
        self.assertEqual(ziel, os.path.join(self.musik, "Michael Jackson", "Bad (1987)", "01 Bad.mp3"))
        t = bestand.lies(ziel)
        self.assertEqual((t["titel"], t["isrc"]), ("Bad", "USSM18700382"))
        self.assertEqual(self.s.wunsch(w["id"])["stand"], "erledigt")
        # Gleiche Qualität nochmal → beiseite
        mp3b = os.path.join(self.eingang, "y.mp3"); ton(mp3b, title="Bad", artist="Michael Jackson", TSRC="USSM18700382")
        self.s.katalog.hole = lambda *_: None   # kein Netz
        self.s.heimat = lambda isrc: dict(INFO)
        self.assertIsNone(self.s.einsortieren(mp3b))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_doppelt", "y.mp3")))
        # FLAC ist besser → ersetzt die MP3, die MP3 geht beiseite
        flac = os.path.join(self.eingang, "z.flac"); ton(flac, title="Bad", artist="Michael Jackson", ISRC="USSM18700382")
        ziel2 = self.s.einsortieren(flac)
        self.assertTrue(ziel2.endswith("01 Bad.flac"))
        self.assertFalse(os.path.exists(ziel))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_doppelt", "01 Bad.mp3")))

    def test_ersetzen_aus(self):
        self.s.ersetzen = False
        w = self.wunsch()
        mp3 = os.path.join(self.eingang, "x.mp3"); ton(mp3)
        ziel = self.s.einsortieren(mp3, w["id"])
        self.s.heimat = lambda isrc: dict(INFO)
        flac = os.path.join(self.eingang, "z.flac"); ton(flac, ISRC="USSM18700382")
        self.assertIsNone(self.s.einsortieren(flac))
        self.assertTrue(os.path.exists(ziel))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_besser", "z.flac")))

    def test_ohne_tags_dateiname(self):
        gesehen = {}
        self.s.erkennen = lambda t: gesehen.update(t) or None
        ordner = os.path.join(self.eingang, "N4C", "New Times"); os.makedirs(ordner)
        p = os.path.join(ordner, "01 - New Times.flac"); ton(p)
        self.s.einsortieren(p)
        self.assertEqual((gesehen["titel"], gesehen["kuenstler"]), ("New Times", "N4C"))

    def test_unklar(self):
        self.s.erkennen = lambda t: None
        p = os.path.join(self.eingang, "?.flac"); ton(p)
        self.assertIsNone(self.s.einsortieren(p))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_unklar", "?.flac")))

    def test_anschluss(self):
        ordner = os.path.join(self.tmp.name, "anschluesse"); os.makedirs(ordner)
        quelle = os.path.join(self.tmp.name, "quelle.flac"); ton(quelle)
        with open(os.path.join(ordner, "probe.py"), "w") as f:
            f.write(f"NAME = 'Probe'\ndef neuer_wunsch(w, o):\n    o.stand(w['id'], 'in_arbeit')\n    o.abliefern({quelle!r}, w['id'])\n")
        a = anschluesse.Anschluesse(self.s, ordner)
        a.neu([self.wunsch()])
        for _ in range(50):
            if self.s.wuensche("erledigt"): break
            time.sleep(0.1)
        w = self.s.wuensche("erledigt")[0]
        self.assertEqual(w["anschluss"], "Probe")
        self.assertTrue(w["pfad"].endswith("01 Bad.flac"))


if __name__ == "__main__":
    unittest.main()
