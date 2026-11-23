"""Anschluss: Notlösung über YouTube (yt-dlp), wenn ein Wunsch nach einiger Zeit noch offen ist.

Läuft nur in „regelmaessig“, damit bessere Quellen (z. B. Prowlarr) zuerst zum Zug kommen.
Einstellungen: ANSCHLUSS_YOUTUBE_WARTEN (Stunden, Vorgabe 6), ANSCHLUSS_YTDLP (Pfad zu yt-dlp, Vorgabe „yt-dlp“).
Braucht yt-dlp, ffmpeg und für YouTube eine JavaScript-Laufzeit (deno), sonst scheitern viele Downloads. Tags und Cover schreibt Ohrwurm beim Einsortieren selbst.
"""
import os
import subprocess
import tempfile
import time

NAME = "YouTube (yt-dlp)"
_VERSUCHT = set()   # je Dienststart nur ein Versuch pro Wunsch


def _lade_von_youtube(wunsch, ordner, ytdlp):
    dauer = wunsch.get("dauer") or 0
    befehl = [ytdlp, f"ytsearch5:{wunsch['kuenstler']} - {wunsch['titel']} Audio", "--no-playlist", "--max-downloads", "1",
              "-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a", "--audio-quality", "0",
              "-o", os.path.join(ordner, "%(id)s.%(ext)s")]
    if dauer:   # nur Videos, deren Länge zum Lied passt (±10 s)
        befehl += ["--match-filter", f"duration >= {int(dauer) - 10} & duration <= {int(dauer) + 10}"]
    r = subprocess.run(befehl, capture_output=True, text=True, timeout=600)
    dateien = [os.path.join(ordner, d) for d in os.listdir(ordner) if d.endswith(".m4a")]
    if not dateien:   # --max-downloads endet mit Code 101, deshalb zählt nur die Datei
        raise RuntimeError((r.stderr.strip().splitlines() or ["Kein passender Treffer"])[-1])
    return dateien[0]


def regelmaessig(offene_wuensche, ohrwurm):
    warten = float(ohrwurm.einstellung("YOUTUBE_WARTEN", "6")) * 3600
    ytdlp = ohrwurm.einstellung("YTDLP", "yt-dlp")
    for w in offene_wuensche:
        if w["id"] in _VERSUCHT or time.time() - (w.get("erstellt") or 0) < warten:
            continue
        _VERSUCHT.add(w["id"])
        ohrwurm.stand(w["id"], "in_arbeit", text="Suche auf YouTube")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ohrwurm.abliefern(_lade_von_youtube(w, tmp, ytdlp), w["id"])
        except Exception as f:
            ohrwurm.stand(w["id"], "fehlgeschlagen", text=f"YouTube: {f}")
