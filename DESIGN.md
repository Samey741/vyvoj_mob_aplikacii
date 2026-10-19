# SportNav – Design Document


---

## 1. Prehľad projektu

SportNav je natívna iOS aplikácia pre držiteľov Multisport karty. Umožňuje nájsť najbližšie akceptované športovisko na mape, filtrovať zariadenia podľa typu aktivity a jedným ťuknutím otvoriť navigáciu v externej mapovej aplikácii.

**Platforma:** iOS 16+  
**Distribúcia:** App Store  
**Jazyk rozhrania:** SK, CZ, EN  
**Backend:** žiadny — aplikácia beží plne offline nad lokálnou SQLite databázou

---

## 2. Princíp fungovania

Aplikácia nemá vlastný server ani cloudový backend. Dáta o športoviskách sa pripravia jednorazovo počas vývoja a zabudujú priamo do aplikácie ako SQLite databáza.

```
[DEV – jednorazovo]
Apify Actor (scraper)
  → surové záznamy (názov, adresa, kategória)
  → Python enrich script
      ├─ Apple Maps Server API  → GPS + otváracie hodiny
      └─ Google Places API (fallback, dev only)
  → export → venues.sqlite

[PRODUKCIA – iOS aplikácia]
venues.sqlite (bundled v app)
  → SQLite reader
  → MapKit + CoreLocation
  → UI (SwiftUI)
  → deep link → Apple Maps / Google Maps
```

---

## 3. Dátová príprava (jednorazový dev proces)

### 3.1 Scraper – Apify Actor

Používame hotový Actor [`janbuchar/multisport-map-scraper`](https://apify.com/janbuchar/multisport-map-scraper), ktorý scrapuje `mapa.multisport.cz` a vracia štruktúrované záznamy.

**Výstup scrapera (jeden záznam):**
```json
{
  "id": 193,
  "title": "Legion Gym",
  "categories": ["Posilovny a silové tréninky"],
  "activities": ["Funkční trénink", "Posilovna"],
  "street": "Husova 100",
  "city": "Jaroměř",
  "phone": "+420 606 182 647",
  "website": "http://legiongym.cz/"
}
```

**Chýba:** GPS súradnice, otváracie hodiny → dopĺňa enrich script.

**Kategórie (slugy pre filter):**

| Slug | Kategória |
|---|---|
| `bazeny-a-vodni-sporty-1` | Bazény a vodní sporty |
| `joga-a-zdravotni-cviceni-3` | Jóga a zdravotní cvičení |
| `lezecke-steny-4` | Lezecké stěny |
| `posilovny-a-silove-treninky-5` | Posilovny a silové tréninky |
| `raketove-a-micove-sporty-7` | Raketové a míčové sporty |
| `skupinove-a-tanecni-lekce-9` | Skupinové a taneční lekce |
| `wellness-a-relax-10` | Wellness a relax |

---

### 3.2 Enrich script – GPS a otváracie hodiny

#### Pravidlo nulových nákladov
> Žiadne platené API volania. Všetky volania sú jednorazové počas vývoja. Do SQLite sa uloží výsledok — v produkcii sa žiadne API nevolá.

#### Primárny zdroj: Apple Maps Server API (zadarmo)

Zadarmo v rámci Apple Developer Program. Prijíma názov + adresu, vracia GPS a otváracie hodiny.

```python
async def enrich_venue_apple(venue: dict, token: str) -> dict:
    query = f"{venue['title']} {venue['street']} {venue['city']}"
    url = "https://maps-api.apple.com/v1/search"
    params = {"q": query, "lang": "sk-SK", "resultTypeFilter": "Poi"}
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params=params)
        data = resp.json()

    if not data.get("results"):
        return venue  # → fallback

    place = data["results"][0]
    venue["lat"] = place["center"]["lat"]
    venue["lon"] = place["center"]["lng"]
    venue["opening_hours"] = place.get("openingHours", {})
    venue["gps_source"] = "apple_maps"
    return venue
```

#### Fallback: Google Places API (jednorazový dev import, $0 v rámci kreditu)

```python
async def enrich_venue_google_fallback(venue: dict) -> dict:
    # Len ak Apple Maps nevrátil výsledok
    # API kľúč existuje IBA v dev prostredí, nikdy v app bundle
    query = f"{venue['title']} {venue['street']} {venue['city']}"
    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": query,
        "inputtype": "textquery",
        "fields": "geometry,opening_hours",
        "key": GOOGLE_API_KEY,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        return venue

    place = candidates[0]
    venue["lat"] = place["geometry"]["location"]["lat"]
    venue["lon"] = place["geometry"]["location"]["lng"]
    venue["opening_hours"] = place.get("opening_hours", {})
    venue["gps_source"] = "google_places_fallback"
    return venue
```

---

### 3.3 SQLite schéma

Výstupom enrich scriptu je `venues.sqlite` zabudovaný priamo do app bundle.

```sql
CREATE TABLE venues (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    street      TEXT,
    city        TEXT,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    phone       TEXT,
    website     TEXT,
    gps_source  TEXT,
    gps_pending INTEGER DEFAULT 0  -- 1 ak GPS nebola nájdená
);

CREATE TABLE categories (
    id    INTEGER PRIMARY KEY,
    slug  TEXT NOT NULL,
    name  TEXT NOT NULL
);

CREATE TABLE venue_categories (
    venue_id    INTEGER REFERENCES venues(id),
    category_id INTEGER REFERENCES categories(id)
);

CREATE TABLE opening_hours (
    venue_id  INTEGER REFERENCES venues(id),
    day       TEXT,   -- 'mon', 'tue', ...
    opens     TEXT,   -- '06:00'
    closes    TEXT    -- '22:00'
);

-- Geospatial index pre rýchle vyhľadávanie v okolí
CREATE INDEX idx_venues_location ON venues(lat, lon);
```

**Zariadenia bez GPS** (`gps_pending = 1`) sa zobrazia iba v zozname, nie na mape.

---

## 4. iOS aplikácia

### 4.1 Architektúra

Aplikácia používa **MVVM** — jednoduchú dvojvrstvovú štruktúru bez zbytočnej komplexnosti:

```
View (SwiftUI)
  └─ ViewModel (ObservableObject)
       └─ Repository (SQLite reader + CoreLocation)
```

Žiadny networking layer, žiadny remote API klient, žiadna autentifikácia.

### 4.2 Technologický stack

| Vrstva | Technológia |
|---|---|
| Jazyk | Swift 5.9+ |
| UI | SwiftUI |
| Mapy | MapKit |
| Poloha & gyroskop | CoreLocation + CMMotionManager |
| Lokálna DB | SQLite (cez `SQLite.swift` knižnicu) |
| Navigácia (externá) | Deep link – `maps://`, `comgooglemaps://` |
| CI/CD | Xcode Cloud |
| Verziovanie | Git + GitHub |

### 4.3 Oprávnenia (Info.plist)

| Kľúč | Dôvod |
|---|---|
| `NSLocationWhenInUseUsageDescription` | Zobrazenie polohy na mape a výpočet vzdialenosti k športoviskám |

Žiadne ďalšie oprávnenia nie sú potrebné. Kamera, mikrofón, fotky, notifikácie — nie sú súčasťou scope.

---

## 5. Obrazovky a tok

### 5.1 Obrazovky

| Obrazovka | Popis |
|---|---|
| **Mapa (Home)** | Hlavná obrazovka — interaktívna mapa s pinmi, geolocate button, tlačidlo filtra |
| **Filter sheet** | Výber kategórie (checklist), slider vzdialenosti (0,5–20 km) |
| **Karta zariadenia** | Bottom sheet po ťuknutí na pin — názov, kategória, vzdialenosť, hodiny, tlačidlo „Navigovať" |

### 5.2 Navigačný tok

```
Spustenie aplikácie
  └─ Povolenie lokácie (systémový dialog, 1× pri prvom spustení)
       └─ Mapa (Home) – piny v okolí
            ├─ Ťuknutie na pin → Karta zariadenia
            │    └─ „Navigovať" → Action sheet (Apple Maps / Google Maps)
            │         └─ Otvorenie externej mapy s cieľom
            └─ Tlačidlo filtra → Filter sheet
                 └─ Výber kategórie / vzdialenosti → Mapa (aktualizovaná)
```

### 5.3 Mapa – detaily

- Centrovaná na aktuálnu GPS polohu
- Modrá bodka = aktuálna poloha + gyroskop (smer pohľadu)
- Piny farebne odlíšené podľa kategórie zariadenia
- Pri oddialení sa piny zhlukujú (clustering)

### 5.4 Navigácia (externá)

Po ťuknutí na „Navigovať" aplikácia:
1. Deteguje nainštalované mapové aplikácie cez `UIApplication.canOpenURL`
2. Ak je dostupná iba jedna → otvorí ju priamo
3. Ak je viac možností → zobrazí `UIActivityViewController` / action sheet

```swift
// Deep link schémy
let appleMaps = "maps://?daddr=\(lat),\(lon)"
let googleMaps = "comgooglemaps://?daddr=\(lat),\(lon)&directionsmode=driving"
let waze = "waze://?ll=\(lat),\(lon)&navigate=yes"
```

---

## 6. Dátový model (Swift)

```swift
struct Venue: Identifiable {
    let id: Int
    let name: String
    let street: String
    let city: String
    let coordinate: CLLocationCoordinate2D
    let categories: [VenueCategory]
    let openingHours: [DaySchedule]
    let phone: String?
    let website: String?
}

enum VenueCategory: String, CaseIterable {
    case fitness    = "posilovny-a-silove-treninky-5"
    case pool       = "bazeny-a-vodni-sporty-1"
    case yoga       = "joga-a-zdravotni-cviceni-3"
    case climbing   = "lezecke-steny-4"
    case racket     = "raketove-a-micove-sporty-7"
    case group      = "skupinove-a-tanecni-lekce-9"
    case wellness   = "wellness-a-relax-10"

    var displayName: String { /* lokalizovaný názov */ }
    var color: Color { /* farba pinu na mape */ }
    var icon: String { /* SF Symbols ikona */ }
}

struct DaySchedule {
    let day: Weekday
    let opens: String   // "06:00"
    let closes: String  // "22:00"
}
```

---

## 7. Mimo scope

Nasledujúce veci **nie sú súčasťou tejto aplikácie** a nebudú implementované:

- Vlastný backend / server
- Používateľské účty a autentifikácia
- Push notifikácie
- Obľúbené / história návštev
- Hodnotenia zariadení
- Skenovanie Multisport karty
- Apple Watch companion app
- Aktualizácia dát po vydaní aplikácie (nová verzia = nový import SQLite)
