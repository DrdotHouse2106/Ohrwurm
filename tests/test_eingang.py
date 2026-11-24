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
        self.s.heimat = lambda isrc, *_: dict(INFO)
        self.assertIsNone(self.s.einsortieren(mp3b))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_doppelt", "y.mp3")))
        # FLAC ist besser → ersetzt die MP3, die MP3 geht beiseite
        flac = os.path.join(self.eingang, "z.flac"); ton(flac, title="Bad", artist="Michael Jackson", ISRC="USSM18700382")
        ziel2 = self.s.einsortieren(flac)
        self.assertTrue(ziel2.endswith("01 Bad.flac"))
        self.assertFalse(os.path.exists(ziel))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_doppelt", "01 Bad.mp3")))

    def test_ersetzen_aus(self):
        """Eigene Dateien bleiben, die bessere Fassung kommt nach _besser."""
        self.s.ersetzen = False
        self.s.heimat = lambda isrc, *_: dict(INFO)
        mp3 = os.path.join(self.eingang, "x.mp3"); ton(mp3, ISRC="USSM18700382")
        ziel = self.s.einsortieren(mp3)
        flac = os.path.join(self.eingang, "z.flac"); ton(flac, ISRC="USSM18700382")
        self.assertIsNone(self.s.einsortieren(flac))
        self.assertTrue(os.path.exists(ziel))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_besser", "z.flac")))

    def test_ersetzen_aus_wunschdatei(self):
        """Was Ohrwurm für einen Wunsch abgelegt hat (z. B. von YouTube), wird auch mit ERSETZEN=aus verbessert."""
        self.s.ersetzen = False
        w = self.wunsch()
        mp3 = os.path.join(self.eingang, "x.mp3"); ton(mp3)
        alt = self.s.einsortieren(mp3, w["id"])
        self.s.heimat = lambda isrc, *_: dict(INFO)
        flac = os.path.join(self.eingang, "z.flac"); ton(flac, ISRC="USSM18700382")
        neu = self.s.einsortieren(flac)
        self.assertTrue(neu.endswith(".flac"))
        self.assertFalse(os.path.exists(alt))
        self.assertTrue(os.path.exists(os.path.join(self.eingang, "_doppelt", os.path.basename(alt))))
        self.assertEqual(self.s.wunsch(w["id"])["pfad"], neu)

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

    def test_haengt(self):
        w = self.wunsch()
        self.s.stand(w["id"], "in_arbeit", anschluss="Probe")
        self.s.db.execute("UPDATE wunsch SET geaendert = 0"); self.s.db.commit()
        anschluesse.Anschluesse(self.s, None).runde()
        self.assertEqual(self.s.wunsch(w["id"])["stand"], "offen")

    def test_regelmaessig_ohne_offene(self):
        ordner = os.path.join(self.tmp.name, "anschluesse"); os.makedirs(ordner)
        with open(os.path.join(ordner, "probe.py"), "w") as f:
            f.write("NAME = 'Probe'\nAUFRUFE = []\ndef regelmaessig(offen, o):\n    AUFRUFE.append(len(offen))\n")
        a = anschluesse.Anschluesse(self.s, ordner)
        a.runde()
        self.assertEqual(a.module[0].AUFRUFE, [0])

    def test_fassung(self):
        """Original statt Jubiläums- oder Drumless-Ausgabe (Daft Punk, Test 24.11.)."""
        def album(id, name, datum): return {"id": id, "attributes": {"name": name, "releaseDate": datum, "artistName": "Daft Punk"}}
        lied = {"id": "s", "attributes": {"name": "Touch", "isrc": "X", "durationInMillis": 498960}, "relationships": {"albums": {"data": [{"id": "2"}, {"id": "1"}]}}}
        alben = {"1": album("1", "Random Access Memories", "2013-05-17"), "2": album("2", "Random Access Memories (10th Anniversary Edition)", "2013-05-17")}
        self.s.katalog.alle = lambda pfad, *_: [lied]
        self.s.katalog.hole = lambda pfad, *_: {"data": [alben[pfad.rsplit("/", 1)[1]]]} if "/albums/" in pfad else None
        self.assertEqual(self.s.heimat("X")["album"], "Random Access Memories")
        self.assertEqual(self.s.heimat("X", "Random Access Memories (10th Anniversary Edition)")["album"], "Random Access Memories (10th Anniversary Edition)")
        songs = [{"attributes": {"name": "Touch", "isrc": i, "durationInMillis": 498960, "albumName": n}}
                 for i, n in (("D", "Random Access Memories (Drumless Edition)"), ("X", "Random Access Memories"))]
        self.s.katalog.hole = lambda pfad, *_: {"results": {"songs": {"data": songs}}} if "/search" in pfad else {"data": [alben[pfad.rsplit("/", 1)[1]]]}
        gefragt = []
        self.s.heimat = lambda isrc, album=None: gefragt.append(isrc)
        self.s.erkennen({"titel": "Touch", "kuenstler": "Daft Punk", "dauer": 498.9})
        self.assertEqual(gefragt, ["X"])


if __name__ == "__main__":
    unittest.main()
