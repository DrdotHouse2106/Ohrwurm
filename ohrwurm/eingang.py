"""Dateien taggen (ohne Neukodierung) und ablegen: Künstler/Album (Jahr)/NN Titel.ext"""
import os, re, shutil, subprocess, tempfile, urllib.request

QUALITAET = {"flac": 4, "alac": 3, "aac": 2, "mp3": 1}


def qualitaet(d: dict) -> tuple:
    return QUALITAET.get(d.get("format") or "", 0), d.get("bitrate") or 0


def sauber(t: str) -> str:
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", t or "Unbekannt").strip(" .")
    return t[:120] or "Unbekannt"


def ziel_pfad(ablage: str, info: dict, endung: str) -> str:
    album = f"{info['album']} ({info['jahr']})" if info.get("jahr") else info["album"]
    nr = f"{info['nummer']:02d} " if info.get("nummer") else ""
    if (info.get("cd") or 1) > 1:
        nr = f"{info['cd']}-{nr}"
    basis = os.path.join(ablage, sauber(info.get("albumkuenstler") or info["kuenstler"]), sauber(album), sauber(nr + info["titel"]))
    pfad, n = basis + endung, 2
    while os.path.exists(pfad):
        pfad, n = f"{basis} ({n}){endung}", n + 1
    return pfad


def schreiben(quelle: str, ziel: str, info: dict):
    """Kopiert den Ton unverändert nach ziel und setzt die Tags neu (alte Tags fallen weg)."""
    endung = os.path.splitext(ziel)[1].lower()
    tags = {"title": info["titel"], "artist": info["kuenstler"], "album_artist": info.get("albumkuenstler") or info["kuenstler"],
            "album": info["album"], "date": info.get("jahr"), "track": info.get("nummer"), "disc": info.get("cd"),
            "genre": info.get("genre"), ("TSRC" if endung == ".mp3" else "ISRC"): info.get("isrc")}
    meta = [x for k, v in tags.items() if v for x in ("-metadata", f"{k}={v}")]
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        bild = None
        if info.get("cover") and endung in (".flac", ".mp3", ".m4a"):
            try:
                bild = os.path.join(tmp, "cover.jpg")
                urllib.request.urlretrieve(info["cover"], bild)
            except Exception:
                bild = None
        temp = os.path.join(tmp, "neu" + endung)
        for mit_bild in ([True, False] if bild else [False]):
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", quelle] + (["-i", bild, "-map", "0:a", "-map", "1:v", "-disposition:v", "attached_pic"] if mit_bild else ["-map", "0:a"])
            cmd += ["-c", "copy", "-map_metadata", "-1"] + meta + (["-id3v2_version", "3"] if endung == ".mp3" else []) + [temp]
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                break
        else:
            raise RuntimeError("ffmpeg konnte die Datei nicht schreiben")
        shutil.move(temp, ziel)


def beiseite(pfad: str, ordner: str) -> str:
    """Verschiebt eine Datei nach ordner (z. B. Eingang/_doppelt), ohne etwas zu überschreiben."""
    os.makedirs(ordner, exist_ok=True)
    basis, endung = os.path.splitext(os.path.join(ordner, os.path.basename(pfad)))
    ziel, n = basis + endung, 2
    while os.path.exists(ziel):
        ziel, n = f"{basis} ({n}){endung}", n + 1
    shutil.move(pfad, ziel)
    return ziel
