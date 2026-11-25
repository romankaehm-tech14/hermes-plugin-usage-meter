# Usage Meter — Hermes Desktop Plugin

Zeigt im Hermes-Desktop direkt unter dem Eingabefeld, was die Sitzung kostet:

```
heute $0,38 · 1,2 Mio Tok   │   Chat $0,05 · 238 k Tok
```

* **heute** — alles seit Mitternacht (Europe/Berlin), über **alle Modelle** und alle
  Sitzungen (Desktop, Telegram, Cron, Web-UI …).
* **Klick** auf die Zeile schaltet die Detailzeile weiter: pro Modell → Top-Chats
  des Tages (Titel, Kosten, Tokens, Quelle) → zu.
* **Chat** — der gerade fokussierte Chat, live aus dem Usage-Stream des Hosts
  (fällt auf die Backend-Abfrage zurück, wenn noch kein Turn gelaufen ist).

## Aufbau

| Pfad | Rolle |
|---|---|
| `desktop/plugin.js` | Desktop-Hälfte: `COMPOSER_AREAS.underside`-Chip unter dem Composer |
| `dashboard/plugin_api.py` | Backend: `GET …/today`, `GET …/top`, `GET …/session/{id}` |
| `dashboard/manifest.json` | Dashboard-Manifest (kein eigener Tab, nur API) |
| `plugin.yaml` | Plugin-Metadaten (nötig, damit `hermes plugins enable` es findet) |

## Datenquelle und Genauigkeit

Gelesen wird `$HERMES_HOME/state.db` (nur lesend): `session_model_usage` je
Sitzung/Modell plus `first_seen`/`last_seen`. Es gibt keinen Ereignis-Log pro
API-Call, deshalb wird eine Zeile, die vor Mitternacht begonnen hat, mit dem
Anteil ihrer Nachrichten im Zeitfenster gewichtet — sonst würde ein tagelanger
Telegram-Chat mit vollem Gewicht in „heute" landen.

`tokens` in der Anzeige = Input + Output + Reasoning. Cache-Reads (typisch das
20-fache) stehen nur in der Detail-Aufschlüsselung (`tokens_with_cache`), sonst
würde die Zahl jede Aussagekraft verlieren.

## Installation

1. **Backend** (läuft auf dem Hermes-Host): Ordner nach `$HERMES_HOME/plugins/usage-meter/`
   legen, `hermes plugins enable usage-meter`, Backend neu starten
   (`hermes serve` bzw. `hermes gateway`), damit die Route mountet.
2. **Desktop-Hälfte**: über den Install-Dialog der App (Git-URL dieses Repos,
   Ziel „Desktop") oder von Hand nach
   `%USERPROFILE%\.hermes\desktop-plugins\usage-meter\plugin.js`.
3. In der App **Capabilities → Plugins** die Desktop-Hälfte einschalten
   (sie ist absichtlich opt-in).

## Endpunkte

```
GET /api/plugins/usage-meter/health
GET /api/plugins/usage-meter/today?tz=Europe/Berlin
GET /api/plugins/usage-meter/top?limit=5&tz=Europe/Berlin
GET /api/plugins/usage-meter/session/{session_id}
```

`today` liefert `totals` (input/output/cache/reasoning/cost/api_calls/tokens),
`by_model[]`, `session_count` und `prorated` (true, wenn Zeilen aus Vortagen
anteilig gezählt wurden).
