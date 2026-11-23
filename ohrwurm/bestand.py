"""Liest die Musikordner (Tags per ffprobe) in SQLite. Nur geänderte Dateien werden neu gelesen."""
import json, os, sqlite3, subprocess
from concurrent.futures import ThreadPoolExecutor

ENDUNGEN = {".flac", ".mp3", ".m4a", ".alac", ".aac", ".ogg", ".opus", ".wav", ".aiff"}
SPALTEN = "pfad, groesse, zeit, isrc, kuenstler, albumkuenstler, titel, album, dauer, format, bitrate"


def vorbereiten(db: sqlite3.Connection):
    db.execute(f"CREATE TABLE IF NOT EXISTS bestand ({SPALTEN}, PRIMARY KEY (pfad))")


def lies(pfad: str) -> dict:
    a = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", pfad],
                       capture_output=True, text=True, timeout=60)
    j = json.loads(a.stdout or "{}")
    f = j.get("format", {})
    tags = {k.lower(): v for k, v in f.get("tags", {}).items()}
    for s in j.get("streams", []):   # Ogg/Opus: Tags am Datenstrom
        tags.update({k.lower(): v for k, v in s.get("tags", {}).items() if k.lower() not in tags})
    ton = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "isrc": (tags.get("isrc") or tags.get("tsrc") or "").split(";")[0].strip().upper() or None,
        "kuenstler": tags.get("artist"), "albumkuenstler": tags.get("album_artist") or tags.get("albumartist"),
        "titel": tags.get("title"), "album": tags.get("album"),
        "dauer": float(f["duration"]) if f.get("duration") else None,
        "format": ton.get("codec_name"), "bitrate": int(f.get("bit_rate") or 0) or None,
    }


def einlesen(db: sqlite3.Connection, ordner: str, melden=print):
    vorbereiten(db)
    alt = {p: (g, z) for p, g, z in db.execute("SELECT pfad, groesse, zeit FROM bestand")}
    gesehen, neu = set(), []
    for wurzel, _, dateien in os.walk(ordner):
        for d in dateien:
            if os.path.splitext(d)[1].lower() in ENDUNGEN:
                p = os.path.join(wurzel, d)
                st = os.stat(p)
                gesehen.add(p)
                if alt.get(p) != (st.st_size, int(st.st_mtime)):
                    neu.append((p, st.st_size, int(st.st_mtime)))
    melden(f"{len(gesehen)} Dateien, {len(neu)} neu oder geändert")
    with ThreadPoolExecutor(8) as pool:
        for n, ((p, g, z), t) in enumerate(zip(neu, pool.map(lambda x: lies(x[0]), neu)), 1):
            db.execute(f"REPLACE INTO bestand ({SPALTEN}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (p, g, z, t["isrc"], t["kuenstler"], t["albumkuenstler"], t["titel"], t["album"], t["dauer"], t["format"], t["bitrate"]))
            if n % 1000 == 0:
                db.commit(); melden(f"  {n}/{len(neu)}")
    weg = [p for p in alt if p.startswith(ordner) and p not in gesehen]
    db.executemany("DELETE FROM bestand WHERE pfad=?", [(p,) for p in weg])
    db.commit()
    melden(f"{len(weg)} entfernt")
