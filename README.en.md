# Ohrwurm

Manages a private music collection using the Apple Music catalog as a template: artist pages like Apple Music, a song-level wish list, every song only once, automatic sorting of new files. Extensions ("Anschlüsse") can be plugged in, e.g. Prowlarr/SABnzbd (Usenet) and YouTube (yt-dlp) as a fallback. The German [README.md](README.md) and [KONZEPT.md](KONZEPT.md) are the reference.

## Installation

1. Requirements: Python 3.11+, `ffmpeg`/`ffprobe`, `openssl` and a MusicKit key (`.p8`) from an Apple developer account.
2. `git clone https://github.com/DrdotHouse2106/Ohrwurm.git`
3. Set the environment variables (see README.md, "Einstellungen"), at least `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_SCHLUESSEL`, `MUSIK`, `ZUGANG`.
4. Scan the collection: `python3 -m ohrwurm einlesen`
5. Run permanently: `python3 -m ohrwurm dienst` (HTTP API on port 8095, inbox folder, extensions), as a systemd service or with Docker.
6. Optional: copy extensions from [anschluesse/](anschluesse/) into the folder set in `ANSCHLUESSE`; their settings come from `ANSCHLUSS_…` variables.

Tests: `python3 -m unittest discover -s tests`

## How it works

- **Wishes:** wish a song, album or artist; only missing songs are added. Extensions pick them up (Usenet first, YouTube after 6 h). Failed downloads are blocklisted and the next best release is tried; lossy files placed by Ohrwurm are upgraded to FLAC later.
- **Sorting:** files in the inbox are recognised via ISRC or artist + title + duration, retagged from Apple data and stored as `Album artist/Album (Year)/NN Title.ext`. Nothing is deleted from the collection; duplicates go to `_doppelt`, better versions to `_besser` (or replace the old file with `ERSETZEN=an`).
- **Following:** follow artists; new releases are checked daily and optionally wished automatically.

## Troubleshooting

| Problem | Fix |
|---|---|
| Extension not loaded | `ANSCHLUESSE` not set; the log must show "Anschluss … geladen". |
| "Einstellung fehlt" | `ANSCHLUSS_…` variables must be in the service environment (`EnvironmentFile` / Docker `environment`), not only in a `.env`. |
| New folders not world-readable despite `UMask=0002` | A default ACL on the music folder overrides the umask. |
| Prowlarr returns nothing | An unreachable indexer can empty the combined search; disable broken indexers. |
| YouTube downloads fail | Keep yt-dlp updated and install a JavaScript runtime (deno). |

## Security

Keep the API on localhost or the LAN (`BIND_ADDR`), use a long random `ZUGANG`, and make the extensions folder writable by root only.

## License

[MIT](LICENSE)
