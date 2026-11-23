# Ohrwurm

Verwaltet eine private Musiksammlung mit dem Katalog von Apple Music als Vorlage: Künstlerseiten wie bei Apple Music, Wunschliste auf Liedebene, jedes Lied nur einmal, Einsortieren neuer Dateien. Anschlüsse lassen sich einbinden (siehe [KONZEPT.md](KONZEPT.md)).

## Stand: Schritt 1 – Katalog und Abgleich (nur lesen)

Ohrwurm schreibt nur in seinen Datenordner, an der Musik ändert es nichts.

```sh
docker run --rm \
  -e APPLE_TEAM_ID=… -e APPLE_KEY_ID=… -e APPLE_SCHLUESSEL=/schluessel.p8 \
  -v /pfad/zum/AuthKey.p8:/schluessel.p8:ro \
  -v /pfad/zur/musik:/musik:ro -v ohrwurm-daten:/daten \
  ghcr.io/drdothouse2106/ohrwurm einlesen          # Bestand einlesen (erstes Mal dauert)

… ghcr.io/drdothouse2106/ohrwurm suche "N4C"       # Apple-ID finden
… ghcr.io/drdothouse2106/ohrwurm bericht 32940 --datei /daten/michael-jackson.md
```

Ohne Docker: `python3 -m ohrwurm …` mit denselben Umgebungsvariablen (`MUSIK`, `DATEN`, `LAND`), dazu `ffprobe` und `openssl`.

Der Bericht zeigt je Künstler die Veröffentlichungen nach Art, welche Lieder vorhanden sind (✓) und fehlen (✗), doppelte Dateien (welche behalten wird) und Dateien, die keinem Lied zugeordnet werden konnten.

Mehrere Musikordner: `MUSIK=/musik/flac:/musik/mp3`.
