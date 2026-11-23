# CLAUDE.md – Ohrwurm

Claude ist für die komplette Entwicklung von Ohrwurm zuständig (Auftrag Marcel, 23.11.2026).

## Für jede Sitzung

1. Zuerst `KONZEPT.md` lesen (Ziel, Anschlüsse, Betrieb, Schritte) und den Ohrwurm-Abschnitt in `FranceTec-Info/offene-punkte.md`.
2. Nach jeder Sitzung: `KONZEPT.md` (Schritte) und `FranceTec-Info/offene-punkte.md` pflegen, Stolpersteine in `FranceTec-Info/wissen/haeufige-probleme.md`.
3. Direkt auf `main` committen und pushen, keine Branches.

## Regeln

- Deutsch in Code-Kommentaren, Texten und Doku. Möglichst wenig Code, nur Standardbibliothek wo möglich.
- Vor jedem Push `python3 -m unittest discover -s tests` (braucht ffmpeg).
- Keine Schlüssel, Tokens oder Adressen mit Zugang ins Repo.

## Betrieb

- Läuft auf **media-stack** als systemd-Dienst `ohrwurm.service`, nicht in Docker. Einstellungen per Drop-in (`systemctl edit ohrwurm`), Schlüssel in `/etc/ohrwurm/anschluesse.env` (600).
- Einspielen und Testen auf dem Server macht die **Heimnetz-Sitzung**. Von hier aus: Code pushen und einen fertigen Prompt für Heimnetz liefern (Schritte, Prüfungen, Rückmeldung ohne Schlüssel).
- Anschlüsse (Vorlagen in `anschluesse/`): Prowlarr (SABnzbd) zuerst, YouTube (yt-dlp) als Notlösung nach 6 h.
- Oberfläche ist Ohrregal (eigenes Repo); Ohrwurm liefert nur die HTTP-Schnittstelle.
