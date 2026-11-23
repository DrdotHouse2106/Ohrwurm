# Ohrwurm

Verwaltet eine private Musiksammlung mit dem Katalog von Apple Music als Vorlage: Künstlerseiten wie bei Apple Music, Wunschliste auf Liedebene, jedes Lied nur einmal, Einsortieren neuer Dateien. Anschlüsse lassen sich einbinden (siehe [KONZEPT.md](KONZEPT.md)).

## Befehle

| Befehl | Was passiert |
|---|---|
| `dienst` | Schnittstelle (Port 8095), Eingangsordner und Anschlüsse laufen dauerhaft |
| `einlesen` | Musikordner einlesen (beim ersten Mal dauert es, danach nur Änderungen) |
| `suche "N4C"` | Apple-ID eines Künstlers finden |
| `bericht 32940 [--datei x.md]` | Abgleich: was es gibt, was da ist, was fehlt, was doppelt ist |
| `wuenschen lied\|album\|kuenstler ID` | Wünsche anlegen (nur Lieder, die noch fehlen) |
| `einsortieren PFAD` | Eine Datei erkennen, taggen und ablegen |
| `folgen [ID] [--automatisch]` | Künstler folgen (ohne ID: Liste). Mit `--automatisch` werden Neuerscheinungen gleich gewünscht |
| `entfolgen ID` | Nicht mehr folgen |
| `neuheiten` / `pruefen` | Neuerscheinungen anzeigen / jetzt suchen (der Dienst sucht täglich von selbst) |

Mit Docker: `docker compose run --rm ohrwurm bericht 32940` (Vorlage: [docker-compose.yml](docker-compose.yml)). Ohne Docker: `python3 -m ohrwurm …`, dazu `ffmpeg`/`ffprobe` und `openssl`.

## Einstellungen

| Variable | Bedeutung |
|---|---|
| `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_SCHLUESSEL` | MusicKit-Schlüssel (Pfad zur .p8-Datei, nur als Datei einbinden) |
| `MUSIK` | Musikordner, mehrere mit `:` getrennt |
| `ABLAGE` | Wohin Neues kommt (Vorgabe: erster Musikordner) |
| `EINGANG` | Überwachter Eingangsordner. Unklares landet in `_unklar`, Doppeltes in `_doppelt` |
| `ANSCHLUESSE` | Ordner mit eigenen Anschlüssen (`*.py`) |
| `ANSCHLUSS_…` | Einstellungen für Anschlüsse (`ohrwurm.einstellung("…")`), in `docker-compose.yml` unter `environment` eintragen |
| `OHRWURM_MELDEN_AN` | Optional: Adresse, an die jeder neue Wunsch gemeldet wird |
| `ZUGANG` | Schlüssel für die Schnittstelle (`Authorization: Bearer …`) |
| `ERSETZEN` | `aus` (Vorgabe): Aus der Sammlung wird nie etwas entfernt; eine bessere Fassung landet in `_besser` und wird nur gemeldet. `an`: Die bessere ersetzt die schlechtere, die schlechtere geht nach `_doppelt`. |
| `BIND_ADDR` | Adresse, auf der die Schnittstelle lauscht (Vorgabe `127.0.0.1`, im Heimnetz die LAN-Adresse; nie öffentlich) |
| `DATEN`, `LAND`, `PORT` | Datenordner, Katalogland (`de`), Port (`8095`) |

## Einsortieren

Erkennung über den ISRC-Tag, sonst über Künstler + Titel + Dauer im Apple-Katalog. Ton wird nicht neu kodiert; die Tags werden komplett aus Apple-Daten neu gesetzt (mit Cover). Ablage: `Albumkünstler/Album (Jahr)/NN Titel.ext`, bei mehreren CDs `2-01 Titel`. Ist das Lied schon in gleicher oder besserer Qualität da, geht die neue Datei nach `_doppelt`. Ist die neue besser (FLAC > ALAC > AAC > MP3), kommt sie nach `_besser`. Nur mit `ERSETZEN=an` ersetzt sie die alte; die alte geht dann nach `_doppelt` (wird nicht gelöscht). Ohne Tags versucht Ohrwurm es über den Pfad `…/Künstler/Album/01 - Titel.ext`.

## Sicherheit

- Anschlüsse sind Python-Code und laufen mit den Rechten des Dienstes. Den Ordner `ANSCHLUESSE` darf nur root bzw. der Dienstbenutzer beschreiben (z. B. `chown root:root`, `chmod 755`, Dateien `644`).
- Die Schnittstelle nur lokal oder im LAN anbieten (`BIND_ADDR`), nie ins Internet freigeben. `ZUGANG` lang und zufällig wählen (`openssl rand -hex 24`).
- Der MusicKit-Schlüssel wird nur als Datei eingebunden und nur an `api.music.apple.com` geschickt.

## Schnittstelle

Alle Aufrufe mit `Authorization: Bearer <ZUGANG>`.

| Aufruf | |
|---|---|
| `GET /api/status` | Anzahl Wünsche je Stand |
| `GET /api/suche?name=…` | Künstler suchen |
| `GET /api/kuenstler/{id}` | Künstlerseite mit Abschnitten, Veröffentlichungen, Liedern (vorhanden, Wunsch) |
| `GET /api/wuensche?stand=offen` | Wünsche (offen, in_arbeit, fehlgeschlagen, erledigt) |
| `POST /api/wuensche` | `{"art": "lied"\|"album"\|"kuenstler", "apple_id": "…"}` |
| `DELETE /api/wuensche/{id}` | Wunsch entfernen |
| `POST /api/wuensche/{id}/stand` | `{"stand": "…", "text": "…"}` |
| `POST /api/eingang` | `{"pfad": "…", "wunsch": id}` – Datei sofort einsortieren |
| `GET /api/folgen` | Gefolgte Künstler |
| `POST /api/folgen` | `{"apple_id": "…", "automatisch": true}` |
| `DELETE /api/folgen/{id}` | Nicht mehr folgen |
| `GET /api/neuheiten[?alle=1]` | Neuerscheinungen (ungesehen bzw. alle) |
| `POST /api/neuheiten/gesehen` | `{"album_ids": […]}` oder `{}` für alle |
