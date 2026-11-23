"""Befehle: dienst · einlesen · suche · bericht · wuenschen · einsortieren · folgen · entfolgen · neuheiten · pruefen"""
import argparse, os, sys, threading
from . import abgleich, anschluesse, bestand, dienst
from .sammlung import Sammlung


def main():
    p = argparse.ArgumentParser(prog="ohrwurm", description=__doc__)
    u = p.add_subparsers(dest="befehl", required=True)
    u.add_parser("dienst", help="Schnittstelle, Eingang und Anschlüsse starten")
    u.add_parser("einlesen", help="Musikordner einlesen")
    u.add_parser("suche", help="Künstler im Apple-Katalog suchen").add_argument("name")
    b = u.add_parser("bericht", help="Abgleich für einen Künstler")
    b.add_argument("kuenstler", help="Apple-ID oder Name")
    b.add_argument("--datei")
    w = u.add_parser("wuenschen", help="Lied, Album oder alle fehlenden Lieder eines Künstlers wünschen")
    w.add_argument("art", choices=["lied", "album", "kuenstler"])
    w.add_argument("apple_id")
    u.add_parser("einsortieren", help="Eine Datei erkennen, taggen und ablegen").add_argument("pfad")
    f = u.add_parser("folgen", help="Künstler folgen (ohne ID: Liste)")
    f.add_argument("apple_id", nargs="?")
    f.add_argument("--automatisch", action="store_true", help="Neuerscheinungen gleich wünschen")
    u.add_parser("entfolgen").add_argument("apple_id")
    u.add_parser("neuheiten", help="Neuerscheinungen anzeigen")
    u.add_parser("pruefen", help="Jetzt nach Neuerscheinungen suchen")
    a = p.parse_args()

    musik = [os.path.abspath(o) for o in os.environ.get("MUSIK", "/musik").split(":")]
    s = Sammlung(os.environ.get("DATEN", "daten"), musik, os.environ.get("ABLAGE"), os.environ.get("EINGANG"), os.environ.get("LAND", "de"))

    if a.befehl == "einlesen":
        for ordner in musik:
            bestand.einlesen(s.db, ordner)
    elif a.befehl == "suche":
        for t in s.katalog.suche_kuenstler(a.name):
            print(t["id"], t["attributes"]["name"], ", ".join(t["attributes"].get("genreNames", [])))
    elif a.befehl == "bericht":
        kid = a.kuenstler if a.kuenstler.isdigit() else (s.katalog.suche_kuenstler(a.kuenstler) or [{}])[0].get("id")
        if not kid:
            sys.exit("Künstler nicht gefunden")
        text = abgleich.bericht(*s.kuenstler_abgleich(kid))
        if a.datei:
            open(a.datei, "w").write(text)
        print(text)
    elif a.befehl == "wuenschen":
        anschluesse.Anschluesse(s, os.environ.get("ANSCHLUESSE"))
        for w in s.wuenschen(a.art, a.apple_id):
            print(w["id"], w["kuenstler"], "–", w["titel"], f"({w['album']})")
    elif a.befehl == "einsortieren":
        if ziel := s.einsortieren(os.path.abspath(a.pfad)):
            print(ziel)
    elif a.befehl == "folgen":
        if a.apple_id:
            s.folgen(a.apple_id, a.automatisch)
        for g in s.gefolgt():
            print(g["apple_id"], g["name"], "– Neuerscheinungen werden automatisch gewünscht" if g["automatisch"] else "– nur Hinweis")
    elif a.befehl == "entfolgen":
        s.entfolgen(a.apple_id)
    elif a.befehl == "neuheiten":
        for n in s.neuheiten():
            print(n["datum"], n["kuenstler"], "–", n["name"], f"({n['art']})")
    elif a.befehl == "pruefen":
        anschluesse.Anschluesse(s, os.environ.get("ANSCHLUESSE"))
        print(f"{len(s.pruefen())} neu")
    elif a.befehl == "dienst":
        zugang = os.environ.get("ZUGANG") or sys.exit("ZUGANG fehlt (Schlüssel für die Schnittstelle)")
        a_ = anschluesse.Anschluesse(s, os.environ.get("ANSCHLUESSE"))
        threading.Thread(target=a_.regelmaessig, daemon=True).start()
        threading.Thread(target=dienst.neuheiten_pruefen, args=(s,), daemon=True).start()
        if s.eingang:
            os.makedirs(s.eingang, exist_ok=True)
            threading.Thread(target=dienst.eingang_ueberwachen, args=(s,), daemon=True).start()
        dienst.starten(s, int(os.environ.get("PORT", "8095")), zugang, os.environ.get("BIND_ADDR", "127.0.0.1"))


if __name__ == "__main__":
    main()
