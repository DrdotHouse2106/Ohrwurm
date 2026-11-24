"""Prowlarr-Anschluss gegen nachgebaute Prowlarr- und SABnzbd-Server."""
import http.server, json, os, shutil, tempfile, threading, unittest, urllib.parse
from ohrwurm import anschluesse
from ohrwurm.sammlung import Sammlung

REL = [{"title": "Daft.Punk-Random.Access.Memories-24BIT-WEB-FLAC-2013-A", "grabs": 9},
       {"title": "Daft.Punk-Random.Access.Memories-WEB-FLAC-2013-B", "grabs": 1},
       {"title": "Daft.Punk-Random.Access.Memories-(Drumless.Edition)-FLAC-2023-D", "grabs": 9},
       {"title": "Daft.Punk-Get.Lucky-(Remixes)-WEB-2013-R", "grabs": 9}]


class Test(unittest.TestCase):
    def setUp(self):
        self.verlauf, self.uebergaben, self.fragen = [], [], []
        test = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}
                if self.path.startswith("/api/v1/indexer"):
                    body = [{"id": 1, "enable": True, "protocol": "usenet", "capabilities": {"categories": [{"id": 3000}]}},
                            {"id": 2, "enable": True, "protocol": "usenet", "capabilities": {"categories": [{"id": 5000, "subCategories": [{"id": 5070}]}]}},
                            {"id": 3, "enable": False, "protocol": "usenet", "capabilities": {"categories": [{"id": 3000}]}}]
                elif self.path.startswith("/api/v1/search"):
                    test.fragen.append(q["query"]); test.indexer = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("indexerIds")
                    body = [{**r, "protocol": "usenet", "downloadUrl": "http://p/?apikey=GEHEIM&x=" + r["title"]} for r in REL]
                elif q.get("mode") == "history":
                    body = {"history": {"slots": test.verlauf}}
                else:
                    test.uebergaben.append(q["nzbname"]); body = {"status": True}
                b = json.dumps(body).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        u = f"http://127.0.0.1:{self.srv.server_port}"
        os.environ.update({"ANSCHLUSS_PROWLARR_URL": u, "ANSCHLUSS_SABNZBD_URL": u, "ANSCHLUSS_PROWLARR_KEY": "k", "ANSCHLUSS_SABNZBD_KEY": "k"})
        self.tmp = tempfile.TemporaryDirectory(); t = self.tmp.name
        os.makedirs(t + "/m"); os.makedirs(t + "/a")
        shutil.copy(os.path.join(os.path.dirname(__file__), "..", "anschluesse", "prowlarr_sabnzbd.py"), t + "/a")
        self.s = Sammlung(t + "/d", [t + "/m"], eingang_ordner=t + "/e")
        self.a = anschluesse.Anschluesse(self.s, t + "/a")
        self.m, self.o = self.a.module[0], anschluesse.Schnittstelle(self.s, "Prowlarr (SABnzbd)")

    def tearDown(self):
        self.srv.shutdown(); self.tmp.cleanup()

    def wunsch(self, i, titel):
        info = {"titel": titel, "kuenstler": "Daft Punk feat. Pharrell Williams", "albumkuenstler": "Daft Punk",
                "album": "Random Access Memories", "album_id": "9", "isrc": f"I{i}"}
        self.s.db.execute("INSERT INTO wunsch (id, isrc, stand, erstellt, geaendert, daten) VALUES (?,?,?,?,?,?)",
                          (i, info["isrc"], "offen", 0, 0, json.dumps(info))); self.s.db.commit()
        return self.s.wunsch(i)

    def test_album_einmal_sperrliste_naechster(self):
        self.m.neuer_wunsch(self.wunsch(1, "Get Lucky"), self.o)
        self.m.neuer_wunsch(self.wunsch(2, "Contact"), self.o)
        self.assertEqual(self.fragen, ["Daft Punk Random Access Memories"])
        self.assertEqual(self.indexer, ["1"])   # nur aktive Usenet-Indexer mit Audio
        self.assertEqual(self.uebergaben, ["[Ohrwurm-1] " + REL[0]["title"]])   # kein Drumless, kein Remix
        self.assertIn("Kommt mit dem Album", self.s.wunsch(2)["text"])
        self.verlauf.insert(0, {"name": self.uebergaben[0], "status": "Failed", "fail_message": "Unvollständig"})
        self.a.runde(); self.a.runde()   # der alte Eintrag löst nur einmal etwas aus
        self.assertEqual(self.uebergaben[1:], ["[Ohrwurm-1] " + REL[1]["title"]])
        self.assertEqual([self.s.wunsch(i)["stand"] for i in (1, 2)], ["in_arbeit", "in_arbeit"])
        self.verlauf.insert(0, {"name": self.uebergaben[1], "status": "Failed"})
        self.a.runde()   # kein weiterer Treffer
        self.assertEqual([self.s.wunsch(i)["stand"] for i in (1, 2)], ["fehlgeschlagen", "fehlgeschlagen"])

    def test_nachruesten_und_von_hand(self):
        self.wunsch(3, "Touch"); self.s.stand(3, "erledigt", pfad="/m/Touch.m4a")
        self.a.runde()
        self.assertEqual(self.uebergaben, ["[Ohrwurm-3] " + REL[0]["title"]])
        self.assertEqual(self.s.wunsch(3)["stand"], "erledigt")
        treffer = self.a.treffer(3)
        self.assertEqual(len(treffer), 4)
        self.assertNotIn("GEHEIM", json.dumps(treffer))   # Download-Adresse mit Prowlarr-Schlüssel bleibt intern
        self.a.nehmen(3, "Prowlarr (SABnzbd)", treffer[-1]["kennung"])
        self.assertIn("Von Hand", self.s.wunsch(3)["text"])

    def test_passt_wortfolge(self):
        """Kurze und Zahlen-Namen treffen nur ganze Wörter (Test 24.11.: „21“ traf „2021“)."""
        p = self.m._passt
        adele = {"titel": "Set Fire to the Rain", "album": "21"}
        self.assertFalse(p({"title": "Adele.Easy.On.Me.2021.FLAC.24.Bit"}, "Adele", "21", adele))
        self.assertTrue(p({"title": "Adele-21-(Deluxe.Edition)-WEB-FLAC-2011"}, "Adele", "21", adele))
        ts = {"titel": "Style", "album": "1989"}
        self.assertTrue(p({"title": "Taylor Swift - 1989 (2014) [FLAC]"}, "Taylor Swift", "1989", ts))
        self.assertFalse(p({"title": "Taylor.Swift-Lover-2019-FLAC"}, "Taylor Swift", "1989", ts))
        self.assertTrue(p({"title": "Simon.and.Garfunkel-Bookends-FLAC"}, "Simon & Garfunkel", "Bookends", {"album": "Bookends"}))
        self.assertTrue(p({"title": "Daft.Punk-Random.Access.Memories-WEB"}, "Daft Punk", "Random Access Memories (Deluxe)", {}))


if __name__ == "__main__":
    unittest.main()
