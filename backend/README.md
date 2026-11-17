# backend – dátová príprava (dev only)

SportNav nemá produkčný server (viď [DESIGN.md](../DESIGN.md), sekcie 2 a 7).
Tento priečinok obsahuje jednorazový dev pipeline, ktorý vyrobí `venues.sqlite`:

- Apify scraper výstup (surové záznamy) – DESIGN.md §3.1
- Python enrich script (OpenStreetMap Nominatim: GPS + otváracie hodiny) – DESIGN.md §3.2
- export do SQLite podľa schémy – DESIGN.md §3.3

Výsledný `venues.sqlite` sa kopíruje do `assets/` Android aplikácie (`frontend/app/src/main/assets/`).

## Spustenie

```
cd backend
pip install -r requirements.txt
python scripts/build_db.py --input data/venues_raw.json --output ../frontend/app/src/main/assets/venues.sqlite
```

Pipeline nepotrebuje žiadny kľúč ani token. Voliteľne sa z prostredia alebo z `backend/.env`
(vzor: `.env.example`) načíta `NOMINATIM_EMAIL` – kontaktný e-mail, ktorý sa posiela Nominatimu
podľa jeho usage policy. `backend/.env` je v `.gitignore` a e-mail sa nikdy nevypisuje do logov.

Nominatim Usage Policy: najviac 1 požiadavka za sekundu (import preto beží ~2 s na zariadenie),
žiadne paralelné požiadavky, import je jednorazový. Pri HTTP 403 (zablokovaná IP) sa beh okamžite
ukončí s kódom 1 a databáza sa nezapíše. Dáta sú © OpenStreetMap contributors (ODbL).

## Testy

```
cd backend
python -m pytest -q
```

Testy nevolajú reálnu sieť (`httpx.MockTransport`).
