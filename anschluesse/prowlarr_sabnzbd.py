"""Anschluss: sucht Wünsche über Prowlarr (Usenet) und gibt den besten Treffer an SABnzbd.

Einstellungen: ANSCHLUSS_PROWLARR_URL, ANSCHLUSS_PROWLARR_KEY, ANSCHLUSS_SABNZBD_URL, ANSCHLUSS_SABNZBD_KEY
SABnzbd legt fertige Downloads der Kategorie „ohrwurm“ in den Eingangsordner von Ohrwurm.
Usenet-Veröffentlichungen sind meist ganze Alben: Gesucht wird zuerst nach dem Album, dann nach dem Lied.
Alle Lieder eines geladenen Albums kommen in die Sammlung; weitere Wünsche aus demselben Album warten darauf.
"""
import json
import re
import urllib.parse
import urllib.request

NAME = "Prowlarr (SABnzbd)"
KATEGORIEN = [3000, 3010, 3040]   # Audio, MP3, Lossless: manche Indexer liefern nur mit Unterkategorie
_BEREITS_UEBERGEBEN = set()
_ALBEN = {}   # album_id → (Titel der Übergabe, wartende Wunsch-IDs)


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


def _suche_prowlarr(query, e):
    params = urllib.parse.urlencode({"query": query, "categories": KATEGORIEN, "type": "search"}, doseq=True)
    treffer = _hole(f"{e['PROWLARR_URL'].rstrip('/')}/api/v1/search?{params}", {"X-Api-Key": e["PROWLARR_KEY"]})
    return [t for t in treffer if t.get("protocol") == "usenet" and t.get("downloadUrl")]


def _bewertung(t):
    titel = (t.get("title") or "").lower()
    punkte = 100 if "flac" in titel else 50 if "mp3" in titel or "320" in titel else 0
    if "24bit" in titel or "24-bit" in titel:
        punkte += 20
    return punkte + min(t.get("grabs") or 0, 10)


def _verarbeite_wunsch(wunsch, ohrwurm, e):
    wid = wunsch["id"]
    if wid in _BEREITS_UEBERGEBEN:
        return
    if wunsch.get("album_id") in _ALBEN:
        titel, wartende = _ALBEN[wunsch["album_id"]]
        _BEREITS_UEBERGEBEN.add(wid)
        wartende.append(wid)
        ohrwurm.stand(wid, "in_arbeit", text=f"Kommt mit dem Album: {titel}")
        return

    suchen = ([f"{wunsch['kuenstler']} {wunsch['album']}"] if wunsch.get("album") else []) + [f"{wunsch['kuenstler']} {wunsch['titel']}"]
    for i, query in enumerate(suchen):
        if ergebnisse := _suche_prowlarr(query, e):
            break
    else:
        ohrwurm.protokoll(f"Nichts gefunden: {' / '.join(suchen)}")
        return   # bleibt offen, „regelmaessig“ versucht es wieder

    for t in sorted(ergebnisse, key=_bewertung, reverse=True):
        if _sab(e, mode="addurl", name=t["downloadUrl"], nzbname=f"[Ohrwurm-{wid}] {t.get('title')}", cat="ohrwurm").get("status") is True:
            _BEREITS_UEBERGEBEN.add(wid)
            if i == 0 and len(suchen) == 2 and wunsch.get("album_id"):
                _ALBEN[wunsch["album_id"]] = (t.get("title"), [])
            ohrwurm.stand(wid, "in_arbeit", text=f"An SABnzbd übergeben: {t.get('title')}")
            return
    ohrwurm.stand(wid, "fehlgeschlagen", text="SABnzbd hat alle Treffer abgelehnt")


def _verlauf_pruefen(ohrwurm, e):
    """Gescheiterte Downloads in SABnzbd melden, sonst bliebe der Wunsch auf „in_arbeit“ stehen."""
    gesehen = set()
    for f in _sab(e, mode="history", search="Ohrwurm-", limit=200)["history"]["slots"]:   # neueste zuerst
        m = re.search(r"Ohrwurm-(\d+)", f.get("name", ""))
        if not m or m[1] in gesehen:
            continue
        gesehen.add(m[1])
        w = ohrwurm.wunsch(int(m[1]))
        if f.get("status") == "Failed" and w and w["stand"] == "in_arbeit" and w["anschluss"] == NAME:
            text = f"SABnzbd: {f.get('fail_message') or 'Download fehlgeschlagen'}"
            for i in [w["id"]] + _ALBEN.pop(w.get("album_id"), (None, []))[1]:
                if (ohrwurm.wunsch(i) or {}).get("stand") == "in_arbeit":
                    ohrwurm.stand(i, "fehlgeschlagen", text=text)


def neuer_wunsch(wunsch, ohrwurm):
    _verarbeite_wunsch(wunsch, ohrwurm, _einstellungen(ohrwurm))


def regelmaessig(offene_wuensche, ohrwurm):
    e = _einstellungen(ohrwurm)
    try:
        _verlauf_pruefen(ohrwurm, e)
    except Exception as f:
        ohrwurm.protokoll(f"SABnzbd-Verlauf: {type(f).__name__}: {f}")
    for wunsch in offene_wuensche:
        try:
            _verarbeite_wunsch(wunsch, ohrwurm, e)
        except Exception as f:   # ein Fehler soll die übrigen Wünsche nicht aufhalten
            ohrwurm.protokoll(f"Wunsch {wunsch['id']}: {type(f).__name__}: {f}")
