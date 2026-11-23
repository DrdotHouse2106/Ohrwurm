"""Befehle: einlesen · suche NAME · bericht ID|NAME [--datei PFAD]"""
import argparse, os, sqlite3, sys
from . import abgleich, apple, bestand


def main():
    p = argparse.ArgumentParser(prog="ohrwurm", description=__doc__)
    u = p.add_subparsers(dest="befehl", required=True)
    u.add_parser("einlesen", help="Musikordner einlesen (MUSIK, mehrere mit : getrennt)")
    u.add_parser("suche", help="Künstler im Apple-Katalog suchen").add_argument("name")
    b = u.add_parser("bericht", help="Abgleich für einen Künstler")
    b.add_argument("kuenstler", help="Apple-ID oder Name")
    b.add_argument("--datei")
    a = p.parse_args()

    daten = os.environ.get("DATEN", "daten")
    os.makedirs(daten, exist_ok=True)
    db = sqlite3.connect(os.path.join(daten, "ohrwurm.db"))
    bestand.vorbereiten(db)

    if a.befehl == "einlesen":
        for ordner in os.environ.get("MUSIK", "/musik").split(":"):
            bestand.einlesen(db, os.path.abspath(ordner))
        return
    k = apple.Katalog(db, os.environ.get("LAND", "de"))
    if a.befehl == "suche":
        for t in k.suche_kuenstler(a.name):
            print(t["id"], t["attributes"]["name"], ", ".join(t["attributes"].get("genreNames", [])))
        return

    kid = a.kuenstler if a.kuenstler.isdigit() else (k.suche_kuenstler(a.kuenstler) or [{}])[0].get("id")
    if not kid:
        sys.exit("Künstler nicht gefunden")
    kuenstler = k.kuenstler(kid)
    ansichten = {v: k.ansicht(kid, v) for v in abgleich.ART}
    veroeff = [(v, al, k.lieder(al["id"])) for v in abgleich.HEIMAT + ("compilation-albums", "live-albums") for al in ansichten[v]]
    lieder = abgleich.lieder_sammeln(veroeff)
    # Mitwirkungen: nur Lieder dieses Künstlers zählen.
    name = abgleich.einfach(kuenstler["attributes"]["name"])
    lieder = [l for l in lieder if name in abgleich.einfach(l.kuenstler)]
    muster = f"%{kuenstler['attributes']['name']}%"
    spalten = [s.strip() for s in bestand.SPALTEN.split(",")]
    dateien = [dict(zip(spalten, z)) for z in db.execute(
        f"SELECT {bestand.SPALTEN} FROM bestand WHERE kuenstler LIKE ? OR albumkuenstler LIKE ?", (muster, muster))]
    rest = abgleich.zuordnen(lieder, dateien)
    text = abgleich.bericht(kuenstler, ansichten, lieder, rest)
    if a.datei:
        open(a.datei, "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
