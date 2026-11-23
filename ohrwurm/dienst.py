"""HTTP-Schnittstelle (für Ohrregal und eigene Anschlüsse) und Eingangsordner."""
import hmac, json, os, re, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import abgleich, bestand


def eingang_ueberwachen(s, alle: int = 30, ruhe: int = 60):
    """Neue Dateien im Eingang einsortieren, sobald sie eine Minute nicht mehr geändert wurden."""
    while True:
        for wurzel, ordner, dateien in os.walk(s.eingang):
            ordner[:] = [o for o in ordner if not o.startswith(("_", "."))]
            for d in dateien:
                p = os.path.join(wurzel, d)
                if os.path.splitext(d)[1].lower() in bestand.ENDUNGEN and time.time() - os.path.getmtime(p) > ruhe:
                    try:
                        ziel = s.einsortieren(p)
                        print(f"Eingang: {d} → {ziel or 'beiseite gelegt'}", flush=True)
                    except Exception:
                        print(f"Eingang: {d}\n{traceback.format_exc()}", flush=True)
        time.sleep(alle)


def kuenstler_json(s, kid: str) -> dict:
    with s.sperre:
        k, ansichten, lieder, rest = s.kuenstler_abgleich(kid)
        gewuenscht = {w["isrc"] or w["apple_id"]: w["stand"] for w in s.wuensche()}
    je_album = {}
    for l in lieder:
        je_album.setdefault(l.heimat["id"], []).append(l)
    def album(a, art):
        at = a["attributes"]
        return {"id": a["id"], "name": at["name"], "jahr": (at.get("releaseDate") or "")[:4], "lieder_gesamt": at.get("trackCount"),
                "cover": (at.get("artwork") or {}).get("url", "").replace("{w}", "600").replace("{h}", "600"),
                "lieder": [{"apple_id": l.roh.get("id"), "isrc": l.isrc, "titel": l.titel, "dauer": l.dauer, "vorhanden": bool(l.dateien),
                            "wunsch": gewuenscht.get(l.isrc or l.roh.get("id"))} for l in je_album.get(a["id"], [])] if art in abgleich.HEIMAT else None}
    return {"id": k["id"], "name": k["attributes"]["name"],
            "zahlen": {"lieder": len(lieder), "vorhanden": sum(1 for l in lieder if l.dateien),
                       "doppelt": sum(1 for l in lieder if len(l.dateien) > 1), "nicht_zugeordnet": len(rest)},
            "abschnitte": [{"art": v, "titel": t, "veroeffentlichungen": [album(a, v) for a in sorted(ansichten[v], key=lambda a: a["attributes"].get("releaseDate") or "", reverse=True)]}
                           for v, t in abgleich.ART.items() if ansichten.get(v)]}


def starten(s, port: int, zugang: str):
    class Anfrage(BaseHTTPRequestHandler):
        def antwort(self, code: int, j):
            text = json.dumps(j, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            self.wfile.write(text)

        def bearbeiten(self, methode: str):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {zugang}"):
                return self.antwort(401, {"text": "Zugang fehlt"})
            pfad, _, abfrage = self.path.partition("?")
            werte = dict(p.split("=", 1) for p in abfrage.split("&") if "=" in p)
            laenge = int(self.headers.get("Content-Length") or 0)
            koerper = json.loads(self.rfile.read(laenge) or b"{}") if laenge else {}
            try:
                if methode == "GET" and pfad == "/api/status":
                    return self.antwort(200, {"wuensche": {st: len(s.wuensche(st)) for st in ("offen", "in_arbeit", "fehlgeschlagen", "erledigt")}})
                if methode == "GET" and pfad == "/api/suche":
                    from urllib.parse import unquote_plus
                    with s.sperre:
                        return self.antwort(200, [{"id": k["id"], "name": k["attributes"]["name"]} for k in s.katalog.suche_kuenstler(unquote_plus(werte.get("name", "")))])
                if methode == "GET" and (m := re.fullmatch(r"/api/kuenstler/(\d+)", pfad)):
                    return self.antwort(200, kuenstler_json(s, m[1]))
                if methode == "GET" and pfad == "/api/wuensche":
                    return self.antwort(200, s.wuensche(werte.get("stand") or werte.get("status")))
                if methode == "POST" and pfad == "/api/wuensche":
                    return self.antwort(200, s.wuenschen(koerper["art"], str(koerper["apple_id"])))
                if methode == "DELETE" and (m := re.fullmatch(r"/api/wuensche/(\d+)", pfad)):
                    s.loeschen(int(m[1])); return self.antwort(200, {"status": "ok"})
                if methode == "POST" and (m := re.fullmatch(r"/api/wuensche/(\d+)/stand", pfad)):
                    s.stand(int(m[1]), koerper["stand"], koerper.get("text", ""), koerper.get("anschluss")); return self.antwort(200, {"status": "ok"})
                if methode == "POST" and pfad == "/api/eingang":
                    return self.antwort(200, {"pfad": s.einsortieren(koerper["pfad"], koerper.get("wunsch"))})
                return self.antwort(404, {"text": "Unbekannt"})
            except (KeyError, ValueError) as f:
                return self.antwort(400, {"text": f"Ungültige Anfrage: {f}"})
            except Exception as f:
                traceback.print_exc()
                return self.antwort(500, {"text": f"{type(f).__name__}: {f}"})

        def do_GET(self): self.bearbeiten("GET")
        def do_POST(self): self.bearbeiten("POST")
        def do_DELETE(self): self.bearbeiten("DELETE")
        def log_message(self, *a): pass

    print(f"Ohrwurm hört auf Port {port}", flush=True)
    ThreadingHTTPServer(("", port), Anfrage).serve_forever()
