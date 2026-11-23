"""Abgleich Katalog ↔ Bestand für einen Künstler. Jedes Lied einmal (ISRC), Heimat = früheste Album/Single."""
import re, unicodedata
from dataclasses import dataclass, field

ART = {"full-albums": "Alben", "singles": "Singles & EPs", "compilation-albums": "Zusammenstellungen",
       "live-albums": "Live", "appears-on-albums": "Mitwirkung"}
HEIMAT = ("full-albums", "singles")   # Nur diese liefern Lieder; der Rest wird nur angezeigt.
QUALITAET = {"flac": 4, "alac": 3, "aac": 2, "mp3": 1}


def einfach(t: str | None) -> str:
    """Vereinfachter Titel/Name für den Vergleich ohne ISRC."""
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s*[\(\[][^)\]]*(feat|with|remaster|version|edit|mono|stereo|deluxe|live)[^)\]]*[\)\]]", "", t)
    t = re.sub(r"\s+-\s+.*(remaster|version|edit|mono|stereo|live).*$", "", t)
    t = re.sub(r"\b(feat|ft)\.?\s.*$", "", t)
    return re.sub(r"[^a-z0-9]+", "", t.replace("&", "and"))


@dataclass
class Lied:
    isrc: str | None
    titel: str
    kuenstler: str
    dauer: float
    heimat: dict              # Veröffentlichung (Apple-Album)
    art: str
    auch_auf: list = field(default_factory=list)
    dateien: list = field(default_factory=list)


def lieder_sammeln(veroeffentlichungen: list[tuple[str, dict, list[dict]]]) -> list[Lied]:
    """veroeffentlichungen: (ansicht, album, titel_liste). Liefert eindeutige Lieder mit Heimat."""
    def rang(e):
        a = e[1]["attributes"]
        return (a.get("releaseDate") or "9999", HEIMAT.index(e[0]) if e[0] in HEIMAT else 9)
    lieder: dict[str, Lied] = {}
    for ansicht, album, titel in sorted(veroeffentlichungen, key=rang):
        for t in titel:
            a = t["attributes"]
            schluessel = a.get("isrc") or f"{einfach(a.get('artistName'))}|{einfach(a['name'])}|{round(a.get('durationInMillis', 0) / 3000)}"
            if schluessel in lieder:
                lieder[schluessel].auch_auf.append(album)
            elif ansicht in HEIMAT:
                lieder[schluessel] = Lied(a.get("isrc"), a["name"], a.get("artistName", ""), a.get("durationInMillis", 0) / 1000, album, ansicht)
    return list(lieder.values())


def zuordnen(lieder: list[Lied], dateien: list[dict]) -> list[dict]:
    """Hängt Dateien an Lieder (ISRC, sonst Titel + Dauer ± 3 s). Gibt nicht zugeordnete Dateien zurück."""
    nach_isrc = {l.isrc: l for l in lieder if l.isrc}
    nach_titel: dict[str, list[Lied]] = {}
    for l in lieder:
        nach_titel.setdefault(einfach(l.titel), []).append(l)
    rest = []
    for d in dateien:
        l = nach_isrc.get(d.get("isrc") or "")
        if not l:
            l = next((k for k in nach_titel.get(einfach(d.get("titel")), [])
                      if not d.get("dauer") or not k.dauer or abs(k.dauer - d["dauer"]) <= 3), None)
        (l.dateien if l else rest).append(d)
    for l in lieder:
        l.dateien.sort(key=lambda d: (QUALITAET.get(d.get("format") or "", 0), d.get("bitrate") or 0), reverse=True)
    return rest


def bericht(kuenstler: dict, ansichten: dict[str, list[dict]], lieder: list[Lied], rest: list[dict]) -> str:
    name = kuenstler["attributes"]["name"]
    da = sum(1 for l in lieder if l.dateien)
    doppelt = [l for l in lieder if len(l.dateien) > 1]
    z = [f"# {name}", "", f"Apple-ID {kuenstler['id']} · {len(lieder)} Lieder aus Alben und Singles · "
         f"**{da} vorhanden, {len(lieder) - da} fehlen** · {len(doppelt)} doppelt · {len(rest)} Dateien nicht zugeordnet", ""]
    je_album: dict[str, list[Lied]] = {}
    for l in lieder:
        je_album.setdefault(l.heimat["id"], []).append(l)
    for ansicht, titel in ART.items():
        alben = ansichten.get(ansicht) or []
        if not alben:
            continue
        z += [f"## {titel} ({len(alben)})", ""]
        for a in sorted(alben, key=lambda a: a["attributes"].get("releaseDate") or ""):
            at = a["attributes"]
            jahr = (at.get("releaseDate") or "")[:4]
            eigene = je_album.get(a["id"], [])
            if ansicht in HEIMAT:
                n = sum(1 for l in eigene if l.dateien)
                z.append(f"- **{at['name']}** ({jahr}) – {n}/{len(eigene)} vorhanden" + (f", {at.get('trackCount', 0) - len(eigene)} Lieder schon woanders" if at.get("trackCount", 0) > len(eigene) else ""))
                z += [f"  - {'✓' if l.dateien else '✗'} {l.titel}" for l in eigene]
            else:
                z.append(f"- {at['name']} ({jahr}) – {at.get('trackCount', '?')} Lieder, nur Anzeige")
        z.append("")
    if doppelt:
        z += ["## Doppelt", ""] + [f"- {l.titel}: behalten {l.dateien[0]['pfad']}" + "".join(f"\n  - überzählig {d['pfad']}" for d in l.dateien[1:]) for l in doppelt] + [""]
    if rest:
        z += ["## Nicht zugeordnet", ""] + [f"- {d['pfad']}" for d in sorted(rest, key=lambda d: d["pfad"])] + [""]
    return "\n".join(z)
