# backend – dátová príprava (dev only)

SportNav nemá produkčný server (viď [DESIGN.md](../DESIGN.md), sekcie 2 a 7).
Tento priečinok obsahuje jednorazový dev pipeline, ktorý vyrobí `venues.sqlite`:

- Apify scraper výstup (surové záznamy) – DESIGN.md §3.1
- Python enrich script (Apple Maps Server API, fallback Google Places) – DESIGN.md §3.2
- export do SQLite podľa schémy – DESIGN.md §3.3

Výsledný `venues.sqlite` sa kopíruje do app bundle v `frontend/`.
API kľúče patria iba sem (dev prostredie), nikdy do app bundle.
