"""Anschluss: sucht Wünsche über Prowlarr (Usenet) und gibt den besten Treffer an SABnzbd.

Einstellungen: ANSCHLUSS_PROWLARR_URL, ANSCHLUSS_PROWLARR_KEY, ANSCHLUSS_SABNZBD_URL, ANSCHLUSS_SABNZBD_KEY
SABnzbd legt fertige Downloads der Kategorie „ohrwurm“ in den Eingangsordner von Ohrwurm.

- Usenet-Veröffentlichungen sind meist ganze Alben: Gesucht wird zuerst nach dem Album, dann nach dem Lied.
  Alle Lieder eines geladenen Albums kommen in die Sammlung; weitere Wünsche aus demselben Album warten darauf.
- Scheitert ein Download in SABnzbd, kommt er auf die Sperrliste und der nächstbeste Treffer wird geladen.
- Offene Wünsche ohne Treffer werden alle 6 h neu gesucht.
- Erledigte Wünsche ohne FLAC (z. B. von YouTube) werden einmal pro Woche nach FLAC durchsucht (höchstens 5 je Runde).
- Von-Hand-Suche: „treffer“ und „nehmen“ (Schnittstelle GET/POST /api/wuensche/<id>/treffer).
"""
import hashlib
import json
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request


NAME = "Prowlarr (SABnzbd)"
KATEGORIEN = [3000, 3010, 3040]   # Audio, MP3, Lossless: manche Indexer liefern nur mit Unterkategorie
UNERWUENSCHT = {"remix", "remixes", "drumless", "instrumental", "instrumentals", "karaoke", "acapella", "tribute", "lullaby", "live", "cover", "covers"}
NEU_SUCHEN = 6 * 3600          # offene Wünsche ohne Treffer
BESSER_SUCHEN = 7 * 24 * 3600  # erledigte Wünsche ohne FLAC
BESSER_JE_RUNDE = 5
_sperre = threading.RLock()
_von_hand = {}   # kennung → Treffer der letzten Von-Hand-Suche (die Download-Adresse enthält den Prowlarr-Schlüssel)


def _hole(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _einstellungen(ohrwurm):
    e = {n: ohrwurm.einstellung(n) for n in ("PROWLARR_URL", "PROWLARR_KEY", "SABNZBD_URL", "SABNZBD_KEY")}
    if not all(e.values()):
        raise RuntimeError("Einstellung fehlt: " + ", ".join("ANSCHLUSS_" + n for n, w in e.items() if not w))
    return e


def _sab(e, **werte):
    return _hole(f"{e['SABNZBD_URL'].rstrip('/')}/api?" + urllib.parse.urlencode({**werte, "apikey": e["SABNZBD_KEY"], "output": "json"}))


def _hauptkuenstler(name):
    """„Daft Punk feat. Pharrell Williams“ → „Daft Punk“ („Simon & Garfunkel“ bleibt)."""
    return re.split(r"\s+(?:feat\.?|ft\.?|with)\s+", name or "", flags=re.I)[0]


def _suchen(wunsch):
    kuenstler = _hauptkuenstler(wunsch["kuenstler"])
    return ([(wunsch.get("albumkuenstler") or kuenstler, wunsch["album"])] if wunsch.get("album") else []) + [(kuenstler, wunsch["titel"])]


def _indexer(e):
    """Nur aktive Usenet-Indexer mit Audio: Ein einzelner nicht erreichbarer Indexer kann sonst die Gesamtsuche leeren."""
    def audio(k): return 3000 <= k.get("id", 0) < 4000 or any(audio(u) for u in k.get("subCategories") or [])
    liste = _hole(f"{e['PROWLARR_URL'].rstrip('/')}/api/v1/indexer", {"X-Api-Key": e["PROWLARR_KEY"]})
    return [i["id"] for i in liste if i.get("enable") and i.get("protocol") == "usenet"
            and any(audio(k) for k in (i.get("capabilities") or {}).get("categories") or [])]


def _prowlarr(kuenstler, name, e):
    werte = {"query": f"{kuenstler} {name}", "categories": KATEGORIEN, "type": "search"}
    if ids := _indexer(e):
        werte["indexerIds"] = ids
    params = urllib.parse.urlencode(werte, doseq=True)
    treffer = _hole(f"{e['PROWLARR_URL'].rstrip('/')}/api/v1/search?{params}", {"X-Api-Key": e["PROWLARR_KEY"]})
    return [t for t in treffer if t.get("protocol") == "usenet" and t.get("downloadUrl")]


def _woerter(text, klammern=False):
    """„Don't Stop (Deluxe)“ → ["dont", "stop"]; ohne Akzente, „&“/„and“ und Klammerzusätze (außer klammern=True)."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("'", "").replace("’", "")
    if not klammern:
        t = re.sub(r"[\(\[][^)\]]*[\)\]]", " ", t)
    return [w for w in re.split(r"[^a-z0-9]+", t) if w and w != "and"]


def _enthaelt(woerter, folge):
    """Ganze Wortfolge, kein Teilstück: „21“ trifft nicht „2021“."""
    return bool(folge) and any(woerter[i:i + len(folge)] == folge for i in range(len(woerter) - len(folge) + 1))


def _passt(t, kuenstler, name, wunsch):
    """Titel enthält Künstler und Album bzw. Lied als Wortfolge, keine Remixe und Sonderausgaben (außer der Wunsch sagt es)."""
    woerter = _woerter(t.get("title"), klammern=True)
    erlaubt = set(_woerter(f"{wunsch.get('titel')} {wunsch.get('album')}", klammern=True))
    return _enthaelt(woerter, _woerter(kuenstler)) and _enthaelt(woerter, _woerter(name)) and not (UNERWUENSCHT & set(woerter)) - erlaubt


def _bewertung(t):
    titel = (t.get("title") or "").lower()
    punkte = 100 if "flac" in titel else 50 if "mp3" in titel or "320" in titel else 0
    if "24bit" in titel or "24-bit" in titel:
        punkte += 20
    return punkte + min(t.get("grabs") or 0, 10)


def _kandidaten(wunsch, ohrwurm, e, nur_flac=False):
    """Passende Treffer, beste zuerst, ohne gesperrte. Gibt (Treffer, ob es die Albumsuche war) zurück."""
    gesperrt = set(ohrwurm.erinnern("gesperrt", []))
    suchen = _suchen(wunsch)
    for i, (k, name) in enumerate(suchen):
        liste = [t for t in _prowlarr(k, name, e) if _passt(t, k, name, wunsch) and t.get("title") not in gesperrt
                 and (not nur_flac or "flac" in t["title"].lower())]
        if liste:
            return sorted(liste, key=_bewertung, reverse=True), i == 0 and len(suchen) == 2
    return [], False


def _uebergeben(wunsch, treffer, album, ohrwurm, e, text):
    """Ersten Treffer, den SABnzbd annimmt, übergeben. Gibt den Titel zurück (None: keiner angenommen)."""
    wid = wunsch["id"]
    for t in treffer:
        if _sab(e, mode="addurl", name=t["downloadUrl"], nzbname=f"[Ohrwurm-{wid}] {t['title']}", cat="ohrwurm").get("status") is True:
            uebergeben = ohrwurm.erinnern("uebergeben", {})
            uebergeben[str(wid)] = t["title"]
            ohrwurm.merken("uebergeben", uebergeben)
            if album and wunsch.get("album_id"):
                alben = ohrwurm.erinnern("alben", {})
                alben[wunsch["album_id"]] = {"titel": t["title"], "wartende": []}
                ohrwurm.merken("alben", alben)
            if text:
                ohrwurm.stand(wid, "in_arbeit", text=f"{text}: {t['title']}")
            return t["title"]
    return None


def _verarbeite_wunsch(wunsch, ohrwurm, e):
    """Gibt False zurück, wenn es keinen (weiteren) Treffer gibt."""
    with _sperre:
        wid, alben = wunsch["id"], ohrwurm.erinnern("alben", {})
        if (a := alben.get(wunsch.get("album_id") or "")) and wid not in a["wartende"]:
            a["wartende"].append(wid)
            ohrwurm.merken("alben", alben)
            ohrwurm.stand(wid, "in_arbeit", text=f"Kommt mit dem Album: {a['titel']}")
            return True
        zuletzt = ohrwurm.erinnern("zuletzt", {})
        zuletzt[str(wid)] = time.time()
        ohrwurm.merken("zuletzt", zuletzt)
        treffer, album = _kandidaten(wunsch, ohrwurm, e)
        if not treffer:
            ohrwurm.protokoll(f"Nichts gefunden: {' / '.join(' '.join(x) for x in _suchen(wunsch))}")
            return False
        if _uebergeben(wunsch, treffer, album, ohrwurm, e, "An SABnzbd übergeben"):
            return True
        ohrwurm.stand(wid, "fehlgeschlagen", text="SABnzbd hat alle Treffer abgelehnt")
        return True


def _verlauf_pruefen(ohrwurm, e):
    """Gescheiterte Downloads sperren und den nächstbesten Treffer laden."""
    gesehen = set()
    for f in _sab(e, mode="history", search="Ohrwurm-", limit=200)["history"]["slots"]:   # neueste zuerst
        m = re.match(r"\[?Ohrwurm-(\d+)\]?\s*(.*)", f.get("name", ""))
        if not m or m[1] in gesehen:
            continue
        gesehen.add(m[1])
        with _sperre:
            uebergeben = ohrwurm.erinnern("uebergeben", {})
            # Nur der zuletzt übergebene Download zählt (Nummern werden nach dem Löschen neu vergeben, alte Einträge bleiben).
            if f.get("status") not in ("Completed", "Failed") or uebergeben.get(m[1]) != m[2]:
                continue
            del uebergeben[m[1]]
            ohrwurm.merken("uebergeben", uebergeben)
            alben = ohrwurm.erinnern("alben", {})
            wartende = [i for k, a in list(alben.items()) if a["titel"] == m[2] for i in alben.pop(k)["wartende"]]
            ohrwurm.merken("alben", alben)
            if f["status"] == "Completed":   # Einsortieren übernimmt Ohrwurm über den Eingang
                continue
            ohrwurm.merken("gesperrt", (ohrwurm.erinnern("gesperrt", []) + [m[2]])[-500:])
            text = f"SABnzbd: {f.get('fail_message') or 'Download fehlgeschlagen'}"
            ohrwurm.protokoll(f"Gesperrt: {m[2]} ({text})")
            for i in [int(m[1])] + wartende:
                x = ohrwurm.wunsch(i)
                if x and x["stand"] == "in_arbeit" and x["anschluss"] == NAME and not _verarbeite_wunsch(x, ohrwurm, e):
                    ohrwurm.stand(i, "fehlgeschlagen", text=f"{text}, kein weiterer Treffer")


def _besser_suchen(ohrwurm, e):
    """Erledigte Wünsche ohne FLAC (z. B. von YouTube) nach FLAC durchsuchen. Der Wunsch bleibt erledigt."""
    besser, n = ohrwurm.erinnern("besser", {}), 0
    for w in ohrwurm.wuensche("erledigt"):
        if n >= BESSER_JE_RUNDE:
            break
        if not w.get("pfad") or w["pfad"].lower().endswith(".flac") or time.time() - besser.get(str(w["id"]), 0) < BESSER_SUCHEN:
            continue
        n += 1
        besser[str(w["id"])] = time.time()
        ohrwurm.merken("besser", besser)
        if w.get("album_id") in ohrwurm.erinnern("alben", {}):
            continue
        treffer, album = _kandidaten(w, ohrwurm, e, nur_flac=True)
        if titel := _uebergeben(w, treffer, album, ohrwurm, e, None):
            ohrwurm.protokoll(f"Bessere Fassung für Wunsch {w['id']}: {titel}")


def neuer_wunsch(wunsch, ohrwurm):
    _verarbeite_wunsch(wunsch, ohrwurm, _einstellungen(ohrwurm))


def regelmaessig(offene_wuensche, ohrwurm):
    e = _einstellungen(ohrwurm)
    for name, schritt in (("SABnzbd-Verlauf", _verlauf_pruefen), ("Bessere Fassung", _besser_suchen)):
        try:
            schritt(ohrwurm, e)
        except Exception as f:
            ohrwurm.protokoll(f"{name}: {type(f).__name__}: {f}")
    zuletzt = ohrwurm.erinnern("zuletzt", {})
    for wunsch in offene_wuensche:
        if time.time() - zuletzt.get(str(wunsch["id"]), 0) < NEU_SUCHEN:
            continue
        try:
            _verarbeite_wunsch(wunsch, ohrwurm, e)
        except Exception as f:   # ein Fehler soll die übrigen Wünsche nicht aufhalten
            ohrwurm.protokoll(f"Wunsch {wunsch['id']}: {type(f).__name__}: {f}")


def treffer(wunsch, ohrwurm):
    """Alle Usenet-Treffer für die Von-Hand-Suche, ohne Filter. Die Kennung ersetzt die Download-Adresse."""
    e, gesperrt, liste = _einstellungen(ohrwurm), set(ohrwurm.erinnern("gesperrt", [])), {}
    for k, name in _suchen(wunsch):
        for t in _prowlarr(k, name, e):
            kennung = hashlib.sha1(t["downloadUrl"].encode()).hexdigest()[:16]
            _von_hand[kennung] = t
            liste[kennung] = ({"kennung": kennung, "titel": t.get("title"), "groesse": t.get("size"), "indexer": t.get("indexer"),
                              "alter_tage": t.get("age"), "grabs": t.get("grabs"), "gesperrt": t.get("title") in gesperrt})
    return sorted(liste.values(), key=lambda x: _bewertung({"title": x["titel"], "grabs": x["grabs"]}), reverse=True)


def nehmen(wunsch, kennung, ohrwurm):
    t = _von_hand[kennung]   # KeyError → 400 „Ungültige Anfrage“
    with _sperre:
        if not _uebergeben(wunsch, [t], False, ohrwurm, _einstellungen(ohrwurm), "Von Hand an SABnzbd übergeben"):
            raise ValueError("SABnzbd hat den Treffer abgelehnt")
