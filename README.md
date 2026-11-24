# Ohrwurm

Verwaltet eine private Musiksammlung mit dem Katalog von Apple Music als Vorlage: Künstlerseiten wie bei Apple Music, Wunschliste auf Liedebene, jedes Lied nur einmal, Einsortieren neuer Dateien. Anschlüsse lassen sich einbinden (siehe [KONZEPT.md](KONZEPT.md)).

English: [README.en.md](README.en.md)

## Installation

1. Voraussetzungen: Python 3.11 oder neuer, `ffmpeg`/`ffprobe`, `openssl` und ein MusicKit-Schlüssel (`.p8`) aus dem Apple-Entwicklerkonto.
2. Repo holen: `git clone https://github.com/DrdotHouse2106/Ohrwurm.git`
3. Einstellungen setzen (siehe unten), mindestens `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_SCHLUESSEL`, `MUSIK`, `ZUGANG`.
4. Sammlung einlesen: `python3 -m ohrwurm einlesen`
5. Dauerhaft starten: `python3 -m ohrwurm dienst`, als systemd-Dienst (siehe unten) oder mit Docker ([docker-compose.yml](docker-compose.yml)).
6. Optional: Anschlüsse aus [anschluesse/](anschluesse/) in den Ordner `ANSCHLUESSE` kopieren (z. B. Prowlarr/SABnzbd, YouTube).

Tests: `python3 -m unittest discover -s tests`

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
| `ANSCHLUSS_…` | Einstellungen für Anschlüsse (`ohrwurm.einstellung("…")`), unter systemd per `EnvironmentFile`, bei Docker in `docker-compose.yml` unter `environment` |
| `OHRWURM_MELDEN_AN` | Optional: Adresse, an die jeder neue Wunsch gemeldet wird |
| `ZUGANG` | Schlüssel für die Schnittstelle (`Authorization: Bearer …`) |
| `ERSETZEN` | `aus` (Vorgabe): Aus der Sammlung wird nie etwas entfernt; eine bessere Fassung landet in `_besser` und wird nur gemeldet. Ausnahme: Dateien, die Ohrwurm selbst für einen Wunsch abgelegt hat (z. B. von YouTube), werden immer durch die bessere ersetzt (die alte geht nach `_doppelt`). `an`: Die bessere ersetzt die schlechtere, die schlechtere geht nach `_doppelt`. |
| `BIND_ADDR` | Adresse, auf der die Schnittstelle lauscht (Vorgabe `127.0.0.1`, im Heimnetz die LAN-Adresse; nie öffentlich) |
| `DATEN`, `LAND`, `PORT` | Datenordner, Katalogland (`de`), Port (`8095`) |

## Betrieb als systemd-Dienst

Einstellungen per Drop-in (`systemctl edit ohrwurm`), Schlüssel in einer eigenen Datei (`root:root`, `600`):

```ini
[Service]
Environment=ANSCHLUESSE=/opt/ohrwurm/anschluesse
EnvironmentFile=/etc/ohrwurm/anschluesse.env
UMask=0002
```

Ohne `ANSCHLUESSE` wird kein Anschluss geladen. `UMask=0002` sorgt dafür, dass neue Ordner und Dateien in der Sammlung für alle lesbar sind (wie die bestehenden). Danach `systemctl daemon-reload && systemctl restart ohrwurm`, im Log (`journalctl -u ohrwurm`) steht je Anschluss „… geladen“.

Beiwerk aus Downloads (nfo, jpg, m3u, sfv, txt) räumt am besten ein Nachbearbeitungsskript in SABnzbd weg, das nur in `[Ohrwurm-…]`-Ordnern löscht (die Bereinigungsliste gilt für alle Kategorien). Leere Unterordner im Eingang entfernt Ohrwurm selbst.

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
| `GET /api/wuensche/{id}/treffer` | Von-Hand-Suche: Treffer aller Anschlüsse (`anschluss`, `kennung`, `titel`, `groesse`, `indexer`, `alter_tage`, `grabs`, `gesperrt`) |
| `POST /api/wuensche/{id}/treffer` | `{"anschluss": "…", "kennung": "…"}` – diesen Treffer laden |
| `POST /api/eingang` | `{"pfad": "…", "wunsch": id}` – Datei sofort einsortieren |
| `GET /api/folgen` | Gefolgte Künstler |
| `POST /api/folgen` | `{"apple_id": "…", "automatisch": true}` |
| `DELETE /api/folgen/{id}` | Nicht mehr folgen |
| `GET /api/neuheiten[?alle=1]` | Neuerscheinungen (ungesehen bzw. alle) |
| `POST /api/neuheiten/gesehen` | `{"album_ids": […]}` oder `{}` für alle |

## Probleme und Lösungen

| Problem | Lösung |
|---|---|
| Anschluss wird nicht geladen | `ANSCHLUESSE` ist nicht gesetzt oder zeigt auf den falschen Ordner. Im Log muss „Anschluss … geladen“ stehen. |
| Anschluss meldet „Einstellung fehlt“ | `ANSCHLUSS_…` steht nur in einer `.env`, nicht in der Umgebung des Dienstes. Unter systemd per `EnvironmentFile`, bei Docker unter `environment`. |
| Neue Ordner nicht für alle lesbar, obwohl `UMask=0002` | Eine Standard-ACL auf dem Musikordner hat Vorrang vor der Umask (`getfacl`). |
| Album landet auf mehrere Ausgaben verteilt (Jubiläums-, Drumless-Ausgabe) | Ohrwurm wählt die Ausgabe mit dem Albumnamen aus der Datei, Sonderfassungen zuletzt. Dateien ohne Album-Tag möglichst vermeiden. |
| Prowlarr findet nichts, obwohl es Treffer gibt | Ein nicht erreichbarer Indexer kann die Gesamtsuche leeren. Der Anschluss fragt nur aktive Usenet-Indexer mit Audio ab; kaputte Indexer in Prowlarr abschalten. |
| Falsches Release bei kurzen Namen („21“, „1989“) | Künstler und Name müssen als ganze Wörter im Titel stehen; ältere Fassungen des Anschlusses ersetzen. |
| YouTube-Downloads scheitern | yt-dlp aktuell halten und eine JavaScript-Laufzeit (deno) installieren. |
| Wunsch hängt auf „in_arbeit“ | Nach 24 h ohne Ergebnis geht er zurück auf „offen“; gescheiterte SABnzbd-Downloads erkennt der Prowlarr-Anschluss nach spätestens 15 min. |

## Lizenz

[MIT](LICENSE) – frei nutzbar, auch kommerziell, ohne Gewähr.
