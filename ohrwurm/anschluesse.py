"""Eigene Anschlüsse: Python-Dateien im Ordner ANSCHLUESSE, die im Dienst mitlaufen (siehe KONZEPT.md)."""
import glob, importlib.util, json, os, threading, time, traceback, urllib.request


class Schnittstelle:
    """Was ein Anschluss von Ohrwurm bekommt."""
    def __init__(self, sammlung, name: str):
        self._s, self.name = sammlung, name

    def stand(self, wunsch_id: int, stand: str, text: str = ""):
        self._s.stand(wunsch_id, stand, text, anschluss=self.name)

    def wunsch(self, wunsch_id: int) -> dict | None:
        """Aktueller Stand eines Wunsches (z. B. um zu prüfen, ob er noch beim eigenen Anschluss liegt)."""
        return self._s.wunsch(wunsch_id)

    def abliefern(self, pfad: str, wunsch_id: int | None = None) -> str | None:
        """Datei einsortieren. Gibt den Pfad in der Sammlung zurück (None: unklar oder schon vorhanden)."""
        return self._s.einsortieren(pfad, wunsch_id)

    def einstellung(self, name: str, vorgabe: str | None = None) -> str | None:
        return os.environ.get("ANSCHLUSS_" + name, vorgabe)

    def protokoll(self, text: str):
        print(f"[{self.name}] {text}", flush=True)


class Anschluesse:
    def __init__(self, sammlung, ordner: str | None):
        self.s, self.module = sammlung, []
        for datei in sorted(glob.glob(os.path.join(ordner, "*.py"))) if ordner else []:
            try:
                spec = importlib.util.spec_from_file_location("anschluss_" + os.path.basename(datei)[:-3], datei)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                m.NAME = getattr(m, "NAME", os.path.basename(datei)[:-3])
                self.module.append(m)
                print(f"Anschluss „{m.NAME}“ geladen", flush=True)
            except Exception:
                print(f"Anschluss {datei} konnte nicht geladen werden:\n{traceback.format_exc()}", flush=True)
        sammlung.bei_neuem_wunsch.append(self.neu)
        if os.environ.get("OHRWURM_MELDEN_AN"):
            sammlung.bei_neuem_wunsch.append(self.melden)

    def _aufruf(self, m, funktion: str, *werte, wunsch_id: int | None = None):
        try:
            getattr(m, funktion)(*werte, Schnittstelle(self.s, m.NAME))
        except Exception as f:
            print(f"Anschluss „{m.NAME}“ ({funktion}):\n{traceback.format_exc()}", flush=True)
            if wunsch_id:
                self.s.stand(wunsch_id, "fehlgeschlagen", f"{type(f).__name__}: {f}", anschluss=m.NAME)

    def neu(self, wuensche: list[dict]):
        """Jeder neue Wunsch geht der Reihe nach an die Anschlüsse, bis einer ihn erledigt hat."""
        def lauf(w):
            for m in self.module:
                if hasattr(m, "neuer_wunsch"):
                    self._aufruf(m, "neuer_wunsch", w, wunsch_id=w["id"])
                    if (self.s.wunsch(w["id"]) or {}).get("stand") == "erledigt":
                        return
        for w in wuensche:
            threading.Thread(target=lauf, args=(w,), daemon=True).start()

    def regelmaessig(self, minuten: int = 15):
        while True:
            time.sleep(minuten * 60)
            self.runde()

    def runde(self, haengt_stunden: float = 24):
        """Hängende Wünsche wieder freigeben, dann alle Anschlüsse mit den offenen Wünschen aufrufen."""
        for w in self.s.wuensche("in_arbeit"):   # z. B. Download abgebrochen: der nächste Anschluss soll es versuchen
            if time.time() - (w["geaendert"] or 0) > haengt_stunden * 3600:
                self.s.stand(w["id"], "offen", f"Seit {haengt_stunden:g} h ohne Ergebnis bei {w['anschluss']}")
        for m in self.module:   # Liste je Anschluss neu holen: was der vorige übernommen hat, ist nicht mehr offen
            offen = self.s.wuensche("offen") + self.s.wuensche("fehlgeschlagen")
            if hasattr(m, "regelmaessig"):   # auch mit leerer Liste, z. B. um laufende Downloads zu prüfen
                self._aufruf(m, "regelmaessig", offen)

    def melden(self, wuensche: list[dict]):
        def senden():
            try:
                urllib.request.urlopen(urllib.request.Request(os.environ["OHRWURM_MELDEN_AN"], json.dumps(wuensche).encode(),
                                                              {"Content-Type": "application/json"}), timeout=15)
            except Exception as f:
                print(f"Meldung an OHRWURM_MELDEN_AN fehlgeschlagen: {f}", flush=True)
        if wuensche:
            threading.Thread(target=senden, daemon=True).start()
