# Ohrwurm – Konzept

Ohrwurm verwaltet eine private Musiksammlung mit dem Katalog von Apple Music als Vorlage. Die Sammlung soll sich anfühlen wie Apple Music: Künstlerseiten nach Art gegliedert, einzelne Lieder wünschbar, jedes Lied nur einmal.

Ohrwurm weiß, was es gibt, was da ist und was gewünscht wird, und sortiert neue Dateien ein. Neue Dateien kommen über den Eingangsordner oder über Anschlüsse (siehe „Anschlüsse“).

## Grundsätze

- **Apple-Katalog ist die Wahrheit** für Künstler, Veröffentlichungen, Arten und Lieder (Land `de`).
- **Liedbasiert:** Gewünscht, gesucht und abgehakt werden Lieder, nicht Alben.
- **Jedes Lied einmal:** Schlüssel ist der ISRC. Ohne ISRC: Künstler + Titel (vereinfacht) + Dauer ± 3 s.
- **Heimat eines Liedes** ist die früheste Veröffentlichung der Art Album oder Single mit diesem ISRC. Zusammenstellungen, Live und Neuauflagen werden angezeigt, liefern aber keine zusätzlichen Lieder.
- **Nur Standardbibliothek:** Python 3, SQLite, `ffprobe`/`ffmpeg` für Tags, `openssl` für den Developer-Token. Keine Zusatzpakete.

## Bausteine

| Baustein | Aufgabe |
|---|---|
| Katalog | Apple Music API: Suche, Künstlerseiten (`full-albums`, `singles`, `compilation-albums`, `live-albums`, `appears-on-albums`, `top-songs`, `latest-release`), Alben mit Liedern. Antworten werden in SQLite zwischengespeichert. 404 = leere Ansicht. |
| Bestand | Liest die Musikordner (Tags per `ffprobe`): ISRC, Künstler, Titel, Album, Dauer, Format. Erkennt Änderungen über Pfad + Größe + Zeit. |
| Abgleich | Ordnet Dateien den Katalog-Liedern zu. Je Lied: `vorhanden`, `gewuenscht`, `fehlt`. Doppelte Dateien zum selben Lied werden gemeldet, die bessere bleibt (FLAC > ALAC > AAC > MP3, dann Bitrate). |
| Folgen | Gefolgte Künstler werden täglich auf Neuerscheinungen geprüft. Neue Lieder landen je nach Einstellung in der Wunschliste oder nur als Hinweis. |
| Wunschliste | Wunsch = Lied, Single, Album oder „alles von Künstler X“. Wird in einzelne Lieder aufgelöst (ohne Doppelte, ohne Lieder, die schon da sind). |
| Eingang | Überwachter Ordner. Neue Dateien werden erkannt (ISRC-Tag, sonst Suche im Katalog über Künstler/Titel/Dauer), mit Katalogdaten und Cover getaggt (ohne Neukodierung) und abgelegt: `Künstler/Album (Jahr)/NN Titel.ext`. Unklares geht nach `Eingang/_unklar`, Doppeltes nach `Eingang/_doppelt`. |
| Schnittstelle | HTTP/JSON für Ohrregal und für eigene Anschlüsse. |

## Anschlüsse (eigene Erweiterungen)

Anschlüsse werden direkt in Ohrwurm eingebunden.

**Eingebaut:** Jede Python-Datei im Ordner `anschluesse/` (auf dem Server, als Laufwerk eingebunden) wird beim Start geladen und läuft im Dienst mit. Sie kann diese Funktionen anbieten, alle freiwillig:

```python
NAME = "Mein Anschluss"

def neuer_wunsch(wunsch, ohrwurm):
    """Wird bei jedem neuen Wunsch aufgerufen (eigener Thread).
    wunsch: dict mit id, isrc, kuenstler, titel, album, upc, dauer, apple_id, art
    ohrwurm.stand(wunsch["id"], "in_arbeit" | "fehlgeschlagen", text="…")
    ohrwurm.abliefern(pfad, wunsch["id"])   # Datei einsortieren, sicher zugeordnet
    ohrwurm.einstellung("SCHLUESSEL")       # liest Umgebungsvariable ANSCHLUSS_SCHLUESSEL
    """

def regelmaessig(offene_wuensche, ohrwurm):
    """Wird alle 15 Minuten mit allen offenen Wünschen aufgerufen (z. B. für Wiederholungen)."""
```

Ohrwurm fängt Fehler je Anschluss ab, protokolliert sie und zeigt in Ohrregal, welcher Anschluss welchen Wunsch bearbeitet. Mehrere Anschlüsse sind möglich; sie werden nacheinander gefragt, bis einer liefert. Die Reihenfolge ergibt sich aus den Dateinamen. „regelmaessig“ bekommt je Anschluss die aktuelle Liste, was ein vorheriger Anschluss übernommen hat (`in_arbeit`), fehlt darin. Vorlagen liegen in `anschluesse/` (Prowlarr/SABnzbd, YouTube als Notlösung).

**Von außen** geht es genauso über HTTP:

1. `GET /api/wuensche?status=offen` oder Meldung an `OHRWURM_MELDEN_AN` bei jedem neuen Wunsch
2. `POST /api/wuensche/{id}/stand` mit `{"stand": "…", "text": "…"}`
3. Datei in den Eingang legen oder `POST /api/eingang` mit `{"pfad": "…", "wunsch": id}`

## Ohrregal

Ohrregal bekommt eine Künstlerseite im Apple-Stil (Alben, Singles & EPs, Zusammenstellungen, Live; vorhandene Lieder hervorgehoben, fehlende ausgegraut mit „Wünschen“), „Folgen“, die Wunschliste mit Stand und den Hinweis auf Neuerscheinungen.

## Betrieb

- Docker-Image aus diesem Repo, Daten in `/daten` (SQLite).
- Einstellungen über Umgebungsvariablen: `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_SCHLUESSEL` (Pfad zur .p8-Datei, als Datei eingebunden, nie im Repo), `MUSIK` (Musikordner, nur lesen bis auf Ablage), `EINGANG`, `OHRWURM_MELDEN_AN` (optional), `ZUGANG` (Schlüssel für die Schnittstelle).
- Developer-Token: ES256-JWT, alle 30 Tage neu erzeugt. Bei 401 einmal neu erzeugen und wiederholen.
- Lidarr kann parallel weiterlaufen. Ohrwurm schreibt nur in Eingang und Ablage.

## Schritte

1. ✓ **Katalog und Abgleich, nur lesen.** Bericht je Künstler: was es bei Apple gibt, was da ist, was fehlt, welche Dateien doppelt sind. Probe mit N4C und Michael Jackson.
2. ✓ **Wunschliste, Schnittstelle, Eingang, Anschlüsse** (Erkennen, Taggen, Ablegen).
3. ✓ **Folgen und Neuerscheinungen.** Beim Folgen gilt alles Bisherige als bekannt; täglich wird nach neuen Alben und Singles gesucht (Vorankündigungen erst ab Erscheinen).
4. **Ohrregal-Oberfläche** (iPhone, später TV).
5. **Apple-Music-Mediathek und Wiedergabelisten** als Vorlage (Music-User-Token nach Anmeldung mit der Apple-ID).
