"""Anschluss: sucht Wünsche über Prowlarr (Usenet) und gibt den besten Treffer an SABnzbd.

Einstellungen (Umgebungsvariablen im Container):
ANSCHLUSS_PROWLARR_URL, ANSCHLUSS_PROWLARR_KEY, ANSCHLUSS_SABNZBD_URL, ANSCHLUSS_SABNZBD_KEY
SABnzbd legt fertige Downloads der Kategorie „ohrwurm“ in den Eingangsordner von Ohrwurm.
"""
import json
import urllib.parse
import urllib.request

NAME = "Prowlarr (SABnzbd)"
_BEREITS_UEBERGEBEN = set()


def _hole(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _suche_prowlarr(query, url, key):
    params = urllib.parse.urlencode({"query": query, "categories": [3000], "type": "search"}, doseq=True)
    treffer = _hole(f"{url.rstrip('/')}/api/v1/search?{params}", {"X-Api-Key": key})
    return [t for t in treffer if t.get("protocol") == "usenet" and t.get("downloadUrl")]


def _bewertung(t):
    titel = (t.get("title") or "").lower()
    punkte = 100 if "flac" in titel else 50 if "mp3" in titel or "320" in titel else 0
    if "24bit" in titel or "24-bit" in titel:
        punkte += 20
    return punkte + min(t.get("grabs") or 0, 10)


def _sende_an_sabnzbd(t, wunsch_id, url, key):
    params = urllib.parse.urlencode({"mode": "addurl", "name": t["downloadUrl"], "nzbname": f"[Ohrwurm-{wunsch_id}] {t.get('title')}",
                                     "cat": "ohrwurm", "apikey": key, "output": "json"})
    return _hole(f"{url.rstrip('/')}/api?{params}").get("status") is True


def _verarbeite_wunsch(wunsch, ohrwurm):
    wid = wunsch["id"]
    if wid in _BEREITS_UEBERGEBEN:
        return
    e = {n: ohrwurm.einstellung(n) for n in ("PROWLARR_URL", "PROWLARR_KEY", "SABNZBD_URL", "SABNZBD_KEY")}
    if not all(e.values()):
        raise RuntimeError("Einstellung fehlt: " + ", ".join("ANSCHLUSS_" + n for n, w in e.items() if not w))

    suchen = [f"{wunsch['kuenstler']} {wunsch['titel']}"] + ([f"{wunsch['kuenstler']} {wunsch['album']}"] if wunsch.get("album") else [])
    for query in suchen:
        ergebnisse = _suche_prowlarr(query, e["PROWLARR_URL"], e["PROWLARR_KEY"])
        if ergebnisse:
            break
    else:
        ohrwurm.protokoll(f"Nichts gefunden: {suchen[0]}")
        return   # bleibt offen, „regelmaessig“ versucht es wieder

    for t in sorted(ergebnisse, key=_bewertung, reverse=True):
        if _sende_an_sabnzbd(t, wid, e["SABNZBD_URL"], e["SABNZBD_KEY"]):
            _BEREITS_UEBERGEBEN.add(wid)
            ohrwurm.stand(wid, "in_arbeit", text=f"An SABnzbd übergeben: {t.get('title')}")
            return
    ohrwurm.stand(wid, "fehlgeschlagen", text="SABnzbd hat alle Treffer abgelehnt")


def neuer_wunsch(wunsch, ohrwurm):
    _verarbeite_wunsch(wunsch, ohrwurm)


def regelmaessig(offene_wuensche, ohrwurm):
    for wunsch in offene_wuensche:
        try:
            _verarbeite_wunsch(wunsch, ohrwurm)
        except Exception as f:   # ein Fehler soll die übrigen Wünsche nicht aufhalten
            ohrwurm.protokoll(f"Wunsch {wunsch['id']}: {type(f).__name__}: {f}")
