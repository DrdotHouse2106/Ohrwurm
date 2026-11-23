"""Apple Music API (Katalog). Developer-Token per openssl, Antworten in SQLite zwischengespeichert."""
import base64, json, os, sqlite3, subprocess, time, urllib.error, urllib.parse, urllib.request

BASIS = "https://api.music.apple.com"
ANSICHTEN = ["full-albums", "singles", "compilation-albums", "live-albums", "appears-on-albums"]


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def der_zu_roh(der: bytes) -> bytes:
    """ECDSA-Signatur von openssl (DER) in das JWT-Format r||s (je 32 Byte)."""
    assert der[0] == 0x30
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    teile = []
    for _ in range(2):
        assert der[i] == 0x02
        n = der[i + 1]
        teile.append(der[i + 2:i + 2 + n].lstrip(b"\0").rjust(32, b"\0"))
        i += 2 + n
    return teile[0] + teile[1]


def token(team: str, schluessel_id: str, schluessel: str, tage: int = 30) -> str:
    jetzt = int(time.time())
    kopf = _b64(json.dumps({"alg": "ES256", "kid": schluessel_id}).encode())
    inhalt = _b64(json.dumps({"iss": team, "iat": jetzt, "exp": jetzt + tage * 86400}).encode())
    daten = f"{kopf}.{inhalt}".encode()
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", schluessel], input=daten,
                         capture_output=True, check=True).stdout
    return f"{kopf}.{inhalt}.{_b64(der_zu_roh(sig))}"


class Katalog:
    def __init__(self, db: sqlite3.Connection, land: str = "de", gueltig_tage: int = 7):
        self.db, self.land, self.gueltig = db, land, gueltig_tage * 86400
        self._token = None
        db.execute("CREATE TABLE IF NOT EXISTS zwischenspeicher (url TEXT PRIMARY KEY, zeit INTEGER, json TEXT)")

    def _neuer_token(self):
        self._token = token(os.environ["APPLE_TEAM_ID"], os.environ["APPLE_KEY_ID"], os.environ["APPLE_SCHLUESSEL"])

    def hole(self, pfad: str) -> dict | None:
        """GET mit Zwischenspeicher. 404 (leere Ansicht) → None. 401 bei neuem Schlüssel: neu versuchen."""
        url = pfad if pfad.startswith("http") else BASIS + pfad
        z = self.db.execute("SELECT zeit, json FROM zwischenspeicher WHERE url=?", (url,)).fetchone()
        if z and time.time() - z[0] < self.gueltig:
            return json.loads(z[1]) if z[1] else None
        for versuch in range(4):
            if not self._token or versuch:
                self._neuer_token()
            try:
                anfrage = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token}"})
                with urllib.request.urlopen(anfrage, timeout=30) as a:
                    text = a.read().decode()
                break
            except urllib.error.HTTPError as f:
                if f.code == 404:
                    text = ""
                    break
                if f.code in (401, 429, 500, 503) and versuch < 3:
                    time.sleep(2 ** versuch)
                    continue
                raise
        self.db.execute("REPLACE INTO zwischenspeicher VALUES (?,?,?)", (url, int(time.time()), text))
        self.db.commit()
        return json.loads(text) if text else None

    def alle(self, pfad: str) -> list[dict]:
        """Alle Seiten einer Liste (über „next“)."""
        ergebnis = []
        while pfad:
            j = self.hole(pfad)
            if not j:
                break
            ergebnis += j.get("data", [])
            n = j.get("next")
            pfad = n and (n if "limit=" in n else n + ("&" if "?" in n else "?") + "limit=100")
        return ergebnis

    def suche_kuenstler(self, name: str) -> list[dict]:
        j = self.hole(f"/v1/catalog/{self.land}/search?" + urllib.parse.urlencode({"term": name, "types": "artists", "limit": 10}))
        return (j or {}).get("results", {}).get("artists", {}).get("data", [])

    def kuenstler(self, id: str) -> dict:
        return self.hole(f"/v1/catalog/{self.land}/artists/{id}")["data"][0]

    def ansicht(self, id: str, ansicht: str) -> list[dict]:
        return self.alle(f"/v1/catalog/{self.land}/artists/{id}/view/{ansicht}?limit=100")

    def lieder(self, album_id: str) -> list[dict]:
        return self.alle(f"/v1/catalog/{self.land}/albums/{album_id}/tracks?limit=100")
