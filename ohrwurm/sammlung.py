"""Kern: Abgleich, Wunschliste und Einsortieren. Alle Zugriffe auf die Datenbank laufen unter einer Sperre."""
import json, os, re, sqlite3, threading, time, urllib.parse
from . import abgleich, apple, bestand, eingang

STAENDE = ("offen", "in_arbeit", "fehlgeschlagen", "erledigt")


FASSUNGEN = {"drumless", "instrumental", "remix", "remixes", "live", "karaoke", "acapella", "acoustic", "demo"}


def _flach(t: str | None) -> str:
    """Albumname zum genauen Vergleich: „(10th Anniversary Edition)“ zählt, anders als bei abgleich.einfach."""
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


class Sammlung:
    def __init__(self, daten: str, musik: list[str], ablage: str | None = None, eingang_ordner: str | None = None, land: str = "de"):
        os.makedirs(daten, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(daten, "ohrwurm.db"), check_same_thread=False)
        self.sperre = threading.RLock()
        self.musik, self.ablage, self.eingang = musik, ablage or musik[0], eingang_ordner
        self.ersetzen = os.environ.get("ERSETZEN", "aus").lower() in ("an", "ja", "1", "true")
        self.katalog = apple.Katalog(self.db, land)
        self.bei_neuem_wunsch = []   # Rückrufe (Anschlüsse, Meldung nach außen)
        bestand.vorbereiten(self.db)
        self.db.execute("""CREATE TABLE IF NOT EXISTS wunsch (id INTEGER PRIMARY KEY, isrc TEXT, stand TEXT, text TEXT,
            anschluss TEXT, erstellt INTEGER, geaendert INTEGER, pfad TEXT, daten TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS folge (kid TEXT PRIMARY KEY, name TEXT, seit INTEGER,
            automatisch INTEGER, bekannt TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS neuheit (album_id TEXT PRIMARY KEY, kid TEXT, kuenstler TEXT, name TEXT,
            art TEXT, datum TEXT, cover TEXT, gefunden INTEGER, gesehen INTEGER DEFAULT 0)""")
        self.db.commit()

    # MARK: Katalog

    def lied_info(self, titel: dict, album: dict) -> dict:
        a, al = titel["attributes"], album["attributes"]
        genre = next((g for g in al.get("genreNames", []) if g not in ("Musik", "Music")), None)
        return {"apple_id": titel["id"], "isrc": a.get("isrc"), "titel": a["name"], "kuenstler": a.get("artistName", ""),
                "album": al["name"], "album_id": album["id"], "albumkuenstler": al.get("artistName"), "upc": al.get("upc"),
                "dauer": a.get("durationInMillis", 0) / 1000,
                "art": "single" if al.get("isSingle") else "zusammenstellung" if al.get("isCompilation") else "album",
                "jahr": (al.get("releaseDate") or "")[:4] or None, "nummer": a.get("trackNumber"), "cd": a.get("discNumber"),
                "genre": genre, "cover": (al.get("artwork") or {}).get("url", "").replace("{w}", "1000").replace("{h}", "1000") or None}

    def heimat(self, isrc: str, album: str | None = None) -> dict | None:
        """Veröffentlichung mit diesem ISRC: zuerst die mit gleichem Albumnamen wie in der Datei,
        sonst die früheste (keine Zusammenstellung), bei gleichem Datum die mit dem kürzesten Namen (keine „Edition“)."""
        k = self.katalog
        kandidaten = []
        for t in k.alle(f"/v1/catalog/{k.land}/songs?filter[isrc]={isrc}"):
            for ref in t.get("relationships", {}).get("albums", {}).get("data", []):
                j = k.hole(f"/v1/catalog/{k.land}/albums/{ref['id']}")
                if j:
                    al = j["data"][0]
                    a = al["attributes"]
                    kandidaten.append(((album is not None and _flach(a["name"]) != _flach(album), a.get("isCompilation", False),
                                        a.get("releaseDate") or "9999", len(a["name"])), t, al))
        return self.lied_info(*min(kandidaten, key=lambda x: x[0])[1:]) if kandidaten else None

    def erkennen(self, t: dict) -> dict | None:
        """Datei-Tags → Katalog-Lied (ISRC, sonst Suche nach Künstler + Titel mit passender Dauer)."""
        if t.get("isrc") and (h := self.heimat(t["isrc"], t.get("album"))):
            return h
        if not t.get("titel"):
            return None
        k = self.katalog
        j = k.hole(f"/v1/catalog/{k.land}/search?" + urllib.parse.urlencode({"term": f"{t.get('kuenstler') or ''} {t['titel']}", "types": "songs", "limit": 10}))
        passend = [s["attributes"] for s in (j or {}).get("results", {}).get("songs", {}).get("data", [])
                   if abgleich.einfach(s["attributes"]["name"]) == abgleich.einfach(t["titel"])
                   and (not t.get("dauer") or abs(s["attributes"].get("durationInMillis", 0) / 1000 - t["dauer"]) <= 3)]
        # Gleiche Länge heißt nicht gleiche Fassung (z. B. Drumless): Albumname der Datei zuerst, Sonderfassungen zuletzt.
        erlaubt = set(re.split(r"[^a-z0-9]+", f"{t['titel']} {t.get('album') or ''}".lower()))
        def rang(a):
            woerter = set(re.split(r"[^a-z0-9]+", f"{a['name']} {a.get('albumName', '')}".lower()))
            return (bool(t.get("album")) and _flach(a.get("albumName")) != _flach(t["album"]), bool((FASSUNGEN & woerter) - erlaubt))
        a = min(passend, key=rang, default=None)
        return (a and a.get("isrc") and self.heimat(a["isrc"], a.get("albumName"))) or None

    def kuenstler_abgleich(self, kid: str):
        k = self.katalog
        kuenstler = k.kuenstler(kid)
        ansichten = {v: k.ansicht(kid, v) for v in abgleich.ART}
        veroeff = [(v, al, k.lieder(al["id"])) for v in abgleich.HEIMAT + ("compilation-albums", "live-albums") for al in ansichten[v]]
        name = abgleich.einfach(kuenstler["attributes"]["name"])
        lieder = [l for l in abgleich.lieder_sammeln(veroeff) if name in abgleich.einfach(l.kuenstler)]
        # Dateien des Künstlers (auch „feat.“, „Nachname, Vorname“) und alle mit passendem ISRC, z. B. auf Samplern.
        n = kuenstler["attributes"]["name"]
        muster = [f"%{n}%"] + ([f"%{n.split()[-1]}, {' '.join(n.split()[:-1])}%"] if " " in n else [])
        bedingung = " OR ".join(["kuenstler LIKE ? OR albumkuenstler LIKE ?"] * len(muster))
        isrcs = [l.isrc for l in lieder if l.isrc]
        dateien = {d["pfad"]: d for d in self._dateien(bedingung, tuple(m for m in muster for _ in (0, 1)))}
        for i in range(0, len(isrcs), 500):
            teil = isrcs[i:i + 500]
            dateien.update({d["pfad"]: d for d in self._dateien(f"isrc IN ({','.join('?' * len(teil))})", tuple(teil))})
        rest = abgleich.zuordnen(lieder, list(dateien.values()))
        return kuenstler, ansichten, lieder, rest

    # MARK: Bestand

    def _dateien(self, bedingung: str, werte: tuple) -> list[dict]:
        spalten = [s.strip() for s in bestand.SPALTEN.split(",")]
        return [dict(zip(spalten, z)) for z in self.db.execute(f"SELECT {bestand.SPALTEN} FROM bestand WHERE {bedingung}", werte)]

    def vorhanden(self, info: dict) -> list[dict]:
        if info.get("isrc") and (d := self._dateien("isrc = ?", (info["isrc"],))):
            return d
        titel = abgleich.einfach(info["titel"])
        return [d for d in self._dateien("kuenstler LIKE ?", (f"%{info['kuenstler'].split(',')[0].split('&')[0].strip()}%",))
                if abgleich.einfach(d["titel"]) == titel and (not d["dauer"] or abs(d["dauer"] - info["dauer"]) <= 3)]

    # MARK: Wunschliste

    def _wunsch(self, z) -> dict:
        return {**json.loads(z[8]), "id": z[0], "stand": z[2], "text": z[3], "anschluss": z[4], "erstellt": z[5], "geaendert": z[6], "pfad": z[7]}

    def wuensche(self, stand: str | None = None) -> list[dict]:
        with self.sperre:
            zeilen = self.db.execute("SELECT * FROM wunsch" + (" WHERE stand = ?" if stand else "") + " ORDER BY id", (stand,) if stand else ())
            return [self._wunsch(z) for z in zeilen]

    def wunsch(self, id: int) -> dict | None:
        with self.sperre:
            z = self.db.execute("SELECT * FROM wunsch WHERE id = ?", (id,)).fetchone()
            return self._wunsch(z) if z else None

    def wuenschen(self, art: str, apple_id: str) -> list[dict]:
        """art: lied | album | kuenstler. Legt je fehlendem Lied einen Wunsch an (ohne Doppelte)."""
        with self.sperre:
            k = self.katalog
            if art == "lied":
                t = k.hole(f"/v1/catalog/{k.land}/songs/{apple_id}")["data"][0]
                info = t["attributes"].get("isrc") and self.heimat(t["attributes"]["isrc"])
                if not info:
                    al = k.hole(f"/v1/catalog/{k.land}/albums/{t['relationships']['albums']['data'][0]['id']}")["data"][0]
                    info = self.lied_info(t, al)
                infos = [info]
            elif art == "album":
                al = k.hole(f"/v1/catalog/{k.land}/albums/{apple_id}")["data"][0]
                infos = [self.lied_info(t, al) for t in k.lieder(apple_id)]
            elif art == "kuenstler":
                _, _, lieder, _ = self.kuenstler_abgleich(apple_id)
                infos = [self.lied_info(l.roh, l.heimat) for l in lieder if not l.dateien and not l.fassungen]
            else:
                raise ValueError("art muss lied, album oder kuenstler sein")
            offen = {w["isrc"] or w["apple_id"] for w in self.wuensche() if w["stand"] != "fehlgeschlagen"}
            neu, jetzt = [], int(time.time())
            for info in infos:
                if (info["isrc"] or info["apple_id"]) in offen or self.vorhanden(info):
                    continue
                offen.add(info["isrc"] or info["apple_id"])
                c = self.db.execute("INSERT INTO wunsch (isrc, stand, erstellt, geaendert, daten) VALUES (?,?,?,?,?)",
                                    (info["isrc"], "offen", jetzt, jetzt, json.dumps(info)))
                neu.append(c.lastrowid)
            self.db.commit()
            neu = [self.wunsch(i) for i in neu]
        for r in self.bei_neuem_wunsch:
            r(neu)
        return neu

    def stand(self, id: int, stand: str, text: str = "", anschluss: str | None = None, pfad: str | None = None):
        if stand not in STAENDE:
            raise ValueError(f"stand muss eins von {STAENDE} sein")
        with self.sperre:
            self.db.execute("UPDATE wunsch SET stand=?, text=?, anschluss=COALESCE(?, anschluss), pfad=COALESCE(?, pfad), geaendert=? WHERE id=?",
                            (stand, text, anschluss, pfad, int(time.time()), id))
            self.db.commit()

    def loeschen(self, id: int):
        with self.sperre:
            self.db.execute("DELETE FROM wunsch WHERE id = ?", (id,))
            self.db.commit()

    # MARK: Folgen

    def _veroeffentlichungen(self, kid: str) -> list[tuple[str, dict]]:
        """Alben und Singles, die schon erschienen sind (frisch vom Katalog)."""
        heute = time.strftime("%Y-%m-%d")
        return [(v, a) for v in abgleich.HEIMAT for a in self.katalog.ansicht(kid, v, frisch=True)
                if (a["attributes"].get("releaseDate") or "9999") <= heute]

    def folgen(self, kid: str, automatisch: bool = False) -> dict:
        """Ab jetzt zählt nur, was neu erscheint; das Bisherige gilt als bekannt."""
        with self.sperre:
            name = self.katalog.kuenstler(kid)["attributes"]["name"]
            bekannt = [a["id"] for _, a in self._veroeffentlichungen(kid)]
            alt = self.db.execute("SELECT bekannt FROM folge WHERE kid = ?", (kid,)).fetchone()
            self.db.execute("REPLACE INTO folge VALUES (?,?,?,?,?)", (kid, name, int(time.time()), int(automatisch),
                            alt[0] if alt else json.dumps(bekannt)))
            self.db.commit()
            return {"apple_id": kid, "name": name, "automatisch": automatisch}

    def entfolgen(self, kid: str):
        with self.sperre:
            self.db.execute("DELETE FROM folge WHERE kid = ?", (kid,))
            self.db.commit()

    def gefolgt(self) -> list[dict]:
        with self.sperre:
            return [{"apple_id": k, "name": n, "seit": s, "automatisch": bool(a)}
                    for k, n, s, a in self.db.execute("SELECT kid, name, seit, automatisch FROM folge ORDER BY name")]

    def neuheiten(self, alle: bool = False) -> list[dict]:
        with self.sperre:
            spalten = ["album_id", "kuenstler_id", "kuenstler", "name", "art", "datum", "cover", "gefunden", "gesehen"]
            return [dict(zip(spalten, z)) for z in self.db.execute(
                "SELECT * FROM neuheit" + ("" if alle else " WHERE gesehen = 0") + " ORDER BY datum DESC")]

    def gesehen(self, album_ids: list[str] | None = None):
        with self.sperre:
            if album_ids is None:
                self.db.execute("UPDATE neuheit SET gesehen = 1")
            else:
                self.db.executemany("UPDATE neuheit SET gesehen = 1 WHERE album_id = ?", [(i,) for i in album_ids])
            self.db.commit()

    def pruefen(self) -> list[dict]:
        """Neuerscheinungen aller gefolgten Künstler suchen. Bei „automatisch“ gleich wünschen."""
        neu = []
        for f in self.gefolgt():
            try:
                with self.sperre:
                    bekannt = set(json.loads(self.db.execute("SELECT bekannt FROM folge WHERE kid = ?", (f["apple_id"],)).fetchone()[0]))
                    jetzt = self._veroeffentlichungen(f["apple_id"])
                    for v, a in jetzt:
                        if a["id"] in bekannt:
                            continue
                        at = a["attributes"]
                        cover = (at.get("artwork") or {}).get("url", "").replace("{w}", "600").replace("{h}", "600")
                        self.db.execute("INSERT OR IGNORE INTO neuheit VALUES (?,?,?,?,?,?,?,?,0)",
                                        (a["id"], f["apple_id"], f["name"], at["name"], abgleich.ART[v], at.get("releaseDate"), cover, int(time.time())))
                        neu.append({"album_id": a["id"], "kuenstler": f["name"], "name": at["name"], "art": abgleich.ART[v], "automatisch": f["automatisch"]})
                    self.db.execute("UPDATE folge SET bekannt = ? WHERE kid = ?", (json.dumps(sorted(bekannt | {a["id"] for _, a in jetzt})), f["apple_id"]))
                    self.db.commit()
            except Exception as fehler:
                print(f"Neuerscheinungen {f['name']}: {fehler}", flush=True)
        for n in neu:
            print(f"Neu: {n['kuenstler']} – {n['name']} ({n['art']})", flush=True)
            if n["automatisch"]:
                try:
                    self.wuenschen("album", n["album_id"])
                except Exception as fehler:
                    print(f"Wunsch {n['name']}: {fehler}", flush=True)
        return neu

    # MARK: Einsortieren

    def einsortieren(self, pfad: str, wunsch_id: int | None = None) -> str | None:
        """Erkennen, taggen, ablegen. Gibt den neuen Pfad zurück, None wenn unklar oder doppelt."""
        with self.sperre:
            neben = os.path.join(self.eingang or os.path.dirname(pfad), "")
            t = bestand.lies(pfad)
            if not t.get("titel"):   # ohne Tags: …/Künstler/Album/01 - Titel.flac
                teile = os.path.normpath(pfad).split(os.sep)
                t["titel"] = re.sub(r"^\s*\d+\s*[-._ ]\s*", "", os.path.splitext(teile[-1])[0]).replace("_", " ").strip()
                if not t.get("kuenstler") and len(teile) >= 3 and not os.path.normpath(teile[-3]) == os.path.normpath(self.eingang or ""):
                    t["kuenstler"] = teile[-3]
            w = self.wunsch(wunsch_id) if wunsch_id else None
            info = w or self.erkennen(t)
            if not w and info and info.get("isrc"):   # Ein Wunsch legt die Fassung fest (z. B. Original statt Jubiläumsausgabe).
                z = self.db.execute("SELECT * FROM wunsch WHERE isrc = ? AND stand != 'erledigt' ORDER BY id LIMIT 1", (info["isrc"],)).fetchone()
                info = self._wunsch(z) if z else info
            if not info:
                eingang.beiseite(pfad, neben + "_unklar")
                print(f"Nicht erkannt: {pfad} → _unklar", flush=True)
                return None
            alt = self.vorhanden(info)
            if alt and max(eingang.qualitaet(d) for d in alt) >= eingang.qualitaet(t):
                eingang.beiseite(pfad, neben + "_doppelt")
                print(f"Schon vorhanden: {alt[0]['pfad']} ({pfad} → _doppelt)", flush=True)
                self._erledigt(info, w, alt[0]["pfad"])
                return None
            if alt and not self.ersetzen:   # Aus der Sammlung wird nichts entfernt: bessere Fassung nur melden.
                eingang.beiseite(pfad, neben + "_besser")
                print(f"Bessere Fassung von {alt[0]['pfad']}: {pfad} → _besser (ERSETZEN ist aus)", flush=True)
                self._erledigt(info, w, alt[0]["pfad"])
                return None
            ziel = eingang.ziel_pfad(self.ablage, info, os.path.splitext(pfad)[1].lower())
            eingang.schreiben(pfad, ziel, info)
            os.remove(pfad)
            for d in alt:   # schlechtere Fassung aus der Sammlung nehmen, nicht löschen
                if os.path.exists(d["pfad"]):
                    eingang.beiseite(d["pfad"], neben + "_doppelt")
                self.db.execute("DELETE FROM bestand WHERE pfad = ?", (d["pfad"],))
            st = os.stat(ziel)
            n = bestand.lies(ziel)
            self.db.execute(f"REPLACE INTO bestand ({bestand.SPALTEN}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (ziel, st.st_size, int(st.st_mtime), info.get("isrc") or n["isrc"], n["kuenstler"], n["albumkuenstler"],
                             n["titel"], n["album"], n["dauer"], n["format"], n["bitrate"]))
            self._erledigt(info, w, ziel)
            return ziel

    def _erledigt(self, info: dict, w: dict | None, pfad: str):
        ids = {w["id"]} if w else set()
        if info.get("isrc"):
            ids |= {z[0] for z in self.db.execute("SELECT id FROM wunsch WHERE isrc = ? AND stand != 'erledigt'", (info["isrc"],))}
        for i in ids:
            self.stand(i, "erledigt", pfad=pfad)
        self.db.commit()
