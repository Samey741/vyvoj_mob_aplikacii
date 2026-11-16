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
    lat         REAL,     -- NULL iff gps_pending = 1
    lon         REAL,     -- NULL iff gps_pending = 1
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

**Zariadenia bez GPS** (`gps_pending = 1`, `lat`/`lon` = NULL) ostávajú v databáze pre budúce použitie, ale aplikácia ich v tejto verzii nenačítava (MVP nemá zoznamovú obrazovku, viď §8).

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
| `LSApplicationQueriesSchemes` = `comgooglemaps`, `waze` | Nutné, aby `UIApplication.canOpenURL` vedel zistiť nainštalované mapové aplikácie (nie je to oprávnenie, žiadny dialóg) |

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
            │    └─ „Navigovať" → Action sheet (Apple Maps / Google Maps / Waze)
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
3. Ak je viac možností → zobrazí action sheet (SwiftUI `confirmationDialog`) so zoznamom dostupných aplikácií

Podporované aplikácie: Apple Maps (vždy dostupné), Google Maps, Waze.

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

---

## 8. Spresnenia návrhu

Rozhodnutia, ktoré dopĺňajú alebo spresňujú sekcie 3–6. Pri rozpore platí táto sekcia.

1. **Zariadenia bez GPS** — `lat`/`lon` sú v SQLite `NULL` a `gps_pending = 1`. `VenueRepository` načítava iba záznamy s `gps_pending = 0`, preto `Venue.coordinate` ostáva neoptional.
2. **Kategórie** — scraper vracia názvy kategórií (napr. `"Posilovny a silové tréninky"`), nie slugy. Backend obsahuje statickú mapu *názov → slug* pre 7 kategórií z `VenueCategory` (§6). Tabuľka `categories` sa naplní práve týmito 7 riadkami. Neznáma kategória sa zaloguje a preskočí, zariadenie sa však uloží.
3. **Apple Maps token** — vývojár dodá *Maps auth token* (JWT z Apple Developer portálu) v premennej prostredia `APPLE_MAPS_AUTH_TOKEN`. Pipeline ho jedenkrát vymení cez `GET https://maps-api.apple.com/v1/token` za access token, ktorý sa potom posiela do `enrich_venue_apple`.
4. **Google fallback** — volá sa iba vtedy, keď Apple Maps nevráti žiadny výsledok. Endpoint *Find Place* vracia v `opening_hours` iba `open_now`, čo je pre offline aplikáciu nepoužiteľné, preto fallback dopĺňa **iba GPS** (`fields=geometry`). Otváracie hodiny ostanú prázdne. Kľúč je v premennej `GOOGLE_API_KEY`. Ak kľúč chýba, fallback sa preskočí.
5. **Otváracie hodiny** — funkcia `normalize_opening_hours` prevedie odpoveď API na zoznam `(day, opens, closes)` s `day ∈ {mon,…,sun}` a časom vo formáte `HH:MM`. Ak štruktúru nevie spracovať, vráti prázdny zoznam (bez výnimky). V aplikácii sa zobrazujú dnešné hodiny, prípadne text „Otváracie hodiny nedostupné".
6. **Mapa** — SwiftUI `Map` na iOS 16 nepodporuje clustering, preto je mapa implementovaná ako `UIViewRepresentable` nad `MKMapView`: `MKMarkerAnnotationView` s `clusteringIdentifier` a `userTrackingMode = .followWithHeading` pre smer pohľadu. Smer sa berie z `CLLocationManager` heading, `CMMotionManager` sa nepoužije.
7. **Filter** — prázdny výber kategórií znamená „všetky". Predvolená vzdialenosť je 5 km, rozsah 0,5–20 km (krok 0,5 km). Vzdialenosť sa počíta cez `CLLocation.distance(from:)`. Ak používateľ nepovolí polohu, mapa sa vycentruje na oblasť všetkých zariadení a filter vzdialenosti sa vypne.
8. **Xcode projekt** — vytvára ho človek ručne v Xcode 16+ (viď §10, krok 4). Používa *synchronized folders*, takže nové `.swift` súbory v `frontend/SportNav/` sa do projektu pridávajú automaticky a agenti nemusia upravovať `project.pbxproj`.
9. **Chyby Apple Maps a strop Google** (spresňuje §8.4, pravidlo nulových nákladov §3.2) — „Apple nevráti žiadny výsledok" znamená **úspešnú odpoveď (HTTP 200) s prázdnym `results`**. Iba vtedy sa volá Google fallback.
   - **401 / 403** z Apple search → `AppleAuthError`. `enrich_all` raz obnoví access token cez `get_apple_access_token(apple_auth_token, client)` (ak je `apple_auth_token` zadaný) a zariadenie zopakuje; ak chyba pretrvá alebo obnova nie je možná, **celý beh sa ukončí výnimkou `AppleAuthError`** (žiadne volania Google za zvyšné zariadenia).
   - **429, 5xx, timeout, nevalidný JSON alebo JSON, ktorý nie je objekt** pre jedno zariadenie → zariadenie sa označí `gps_pending = 1` **bez volania Google**, chyba sa zaloguje a beh pokračuje.
   - **Strop Google** — `enrich_all(..., max_google_calls=500)`. Po dosiahnutí stropu sa ďalšie zariadenia bez Apple výsledku označia `gps_pending = 1` bez volania Google a raz sa zaloguje varovanie.

---

## 9. Dotknuté súbory a moduly

### 9.1 Backend — dátový pipeline (Python 3.11+, iba dev)

```
backend/
├── requirements.txt              # httpx, pytest
├── .env.example                  # APPLE_MAPS_AUTH_TOKEN=, GOOGLE_API_KEY=
├── data/
│   └── venues_raw.json           # export z Apify Actora (ukladá človek v kroku 9)
├── sportnav_data/
│   ├── __init__.py
│   ├── categories.py             # CATEGORY_SLUGS: dict[názov, slug], CATEGORIES: list[(slug, name)]
│   ├── opening_hours.py          # normalize_opening_hours(raw) -> list[tuple[str, str, str]]
│   ├── enrich.py                 # get_apple_access_token, enrich_venue_apple,
│   │                             # enrich_venue_google_fallback, enrich_venue, enrich_all
│   └── export.py                 # create_schema(conn), export_venues(venues, path)
├── scripts/
│   └── build_db.py               # CLI: --input data/venues_raw.json --output <cesta>.sqlite
└── tests/
    ├── fixtures/                 # vzorové odpovede Apple / Google / Apify
    ├── test_categories.py
    ├── test_opening_hours.py
    ├── test_enrich.py
    └── test_export.py
```

Koreňový `.gitignore`: `backend/.env`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.DS_Store`, `xcuserdata/`, `DerivedData/`.

**Rozhrania (Python):**

```python
async def get_apple_access_token(auth_token: str, client: httpx.AsyncClient) -> str
async def enrich_venue_apple(venue: dict, token: str, client: httpx.AsyncClient) -> dict
async def enrich_venue_google_fallback(venue: dict, api_key: str, client: httpx.AsyncClient) -> dict
async def enrich_venue(venue: dict, apple_token: str, google_key: str | None,
                       client: httpx.AsyncClient) -> dict   # Apple → Google → gps_pending
async def enrich_all(venues: list[dict], apple_token: str, google_key: str | None,
                     client: httpx.AsyncClient, concurrency: int = 5,
                     apple_auth_token: str | None = None,
                     max_google_calls: int = 500) -> list[dict]   # §8.9
class AppleAuthError(Exception)   # 401/403 z Apple, §8.9
def normalize_opening_hours(raw: object) -> list[tuple[str, str, str]]
def create_schema(conn: sqlite3.Connection) -> None          # schéma §3.3
def export_venues(venues: list[dict], path: str) -> None     # vytvorí schému a zapíše dáta
```

`httpx.AsyncClient` sa do funkcií odovzdáva parametrom (oproti ukážkam v §3.2), aby sa dal v testoch nahradiť cez `httpx.MockTransport`. Obohatený záznam má navyše kľúče `lat`, `lon`, `opening_hours` (normalizovaný zoznam), `gps_source` (`apple_maps` | `google_places_fallback` | `None`) a `gps_pending` (0/1).

### 9.2 Frontend — iOS aplikácia (Swift 5.9+, iOS 16+)

```
frontend/
├── SportNav.xcodeproj
├── SportNav/
│   ├── SportNavApp.swift
│   ├── Info.plist                       # §4.3
│   ├── Models/
│   │   ├── Venue.swift                  # Venue, DaySchedule, Weekday (§6)
│   │   └── VenueCategory.swift
│   ├── Data/
│   │   └── VenueRepository.swift        # protocol VenueRepository + SQLiteVenueRepository
│   ├── Services/
│   │   ├── LocationService.swift        # CLLocationManager wrapper (poloha + heading)
│   │   └── NavigationService.swift      # deep linky + detekcia dostupných aplikácií
│   ├── ViewModels/
│   │   ├── MapViewModel.swift           # načítanie, filtrovanie, výber zariadenia
│   │   └── FilterState.swift
│   ├── Views/
│   │   ├── MapScreen.swift
│   │   ├── VenueMapView.swift           # UIViewRepresentable nad MKMapView (clustering)
│   │   ├── FilterSheet.swift
│   │   └── VenueCardSheet.swift
│   └── Resources/
│       ├── venues.sqlite                # výstup backend/scripts/build_db.py
│       └── Localizable.xcstrings        # sk, cs, en
└── SportNavTests/
    ├── Fixtures/test_venues.sqlite      # malá DB vytvorená backendom (5–10 zariadení)
    ├── VenueRepositoryTests.swift
    ├── MapViewModelTests.swift
    └── NavigationServiceTests.swift
```

**Rozhrania (Swift):**

```swift
protocol VenueRepository {
    func loadVenues() throws -> [Venue]          // iba gps_pending = 0
}

struct FilterState: Equatable {
    var categories: Set<VenueCategory> = []      // prázdne = všetky
    var maxDistanceKm: Double = 5                // 0.5 ... 20
}

enum MapApp: CaseIterable { case appleMaps, googleMaps, waze }

protocol URLOpening { func canOpenURL(_ url: URL) -> Bool }   // UIApplication; v testoch mock

struct NavigationService {
    func availableApps(using opener: URLOpening) -> [MapApp]   // appleMaps vždy prvá
    func url(for app: MapApp, to coordinate: CLLocationCoordinate2D) -> URL
}

@MainActor final class MapViewModel: ObservableObject {
    @Published private(set) var visibleVenues: [Venue]
    @Published var filter: FilterState
    @Published var selectedVenue: Venue?
    init(repository: VenueRepository)
    func updateUserLocation(_ location: CLLocation?)
    func distance(to venue: Venue) -> CLLocationDistance?
}

enum Weekday: String, CaseIterable { case mon, tue, wed, thu, fri, sat, sun }
```

---

## 10. Poradie implementácie

Každý krok sa dá samostatne implementovať a overiť príkazom `/implement DESIGN.md <číslo kroku>`.

| # | Krok | Kto | Výstup | Overenie |
|---|---|---|---|---|
| 1 | **Backend základ** — `requirements.txt`, `.env.example`, koreňový `.gitignore`, `sportnav_data/__init__.py`, `categories.py`, `opening_hours.py` + testy | agent | moduly §9.1 | `pytest` (categories, opening_hours) |
| 2 | **Enrich** — `enrich.py`: Apple token, Apple search, Google fallback, `gps_pending`, `enrich_all` s obmedzením súbežnosti + testy s `httpx.MockTransport` | agent | `enrich.py` | `pytest` (bez reálnej siete) |
| 3 | **Export + CLI** — `export.py` (schéma presne podľa §3.3), `scripts/build_db.py`, testovacia fixture DB `frontend/SportNavTests/Fixtures/test_venues.sqlite` + testy | agent | `export.py`, `build_db.py`, fixture DB | `pytest` |
| 4 | **Xcode projekt** — Xcode 16+ → iOS App, SwiftUI, názov `SportNav`, uložiť do `frontend/`, deployment target iOS 16, unit test target `SportNavTests`, SPM balík `SQLite.swift`. Commitnúť. | **človek (macOS)** | `frontend/SportNav.xcodeproj` | projekt sa zbuildí v Xcode |
| 5 | **Modely + Repository** — `Venue.swift`, `VenueCategory.swift` (displayName, color, SF Symbol ikona), `VenueRepository.swift` + testy nad fixture DB | agent (macOS) | §9.2 Models, Data | `xcodebuild test` |
| 6 | **Služby** — `LocationService.swift`, `NavigationService.swift` (§5.4, §8.6) + testy NavigationService | agent (macOS) | §9.2 Services | `xcodebuild test` |
| 7 | **ViewModel** — `FilterState`, `MapViewModel` (filter podľa kategórie a vzdialenosti, §8.7) + testy | agent (macOS) | §9.2 ViewModels | `xcodebuild test` |
| 8 | **UI** — `MapScreen`, `VenueMapView` (clustering, heading, farby pinov), `FilterSheet`, `VenueCardSheet`, `Info.plist` (§4.3), `Localizable.xcstrings` (sk/cs/en) | agent (macOS) | §9.2 Views, Resources | `xcodebuild build` + manuálny checklist §11.3 |
| 9 | **Reálne dáta** — spustiť Apify Actor, uložiť `backend/data/venues_raw.json`, spustiť `python scripts/build_db.py --input data/venues_raw.json --output ../frontend/SportNav/Resources/venues.sqlite` s reálnymi kľúčmi | **človek** | `venues.sqlite` v bundli | počet záznamov, podiel `gps_pending` (§12) |

Kroky 1–3 sa dajú robiť na Windows aj macOS. Kroky 5–8 vyžadujú macOS s Xcode.

---

## 11. Testovacia stratégia

### 11.1 Backend (pytest)

Príkaz: `cd backend && python -m pytest -q`

Testy nesmú volať reálnu sieť. HTTP sa simuluje cez `httpx.MockTransport` s fixtures v `tests/fixtures/`.

| Oblasť | Testované prípady |
|---|---|
| `categories` | všetkých 7 názvov → správny slug; neznámy názov → preskočený (log), zariadenie ostáva |
| `opening_hours` | Google `periods` formát → `("mon", "06:00", "22:00")`; nočná prevádzka cez polnoc; `None` / neznámy formát → `[]` bez výnimky |
| `enrich` | Apple vráti výsledok → `gps_source = "apple_maps"`; Apple prázdne → Google fallback; oba prázdne → `gps_pending = 1`, `lat/lon = None`; chýba `GOOGLE_API_KEY` → fallback sa nevolá; HTTP chyba (5xx/timeout) pri jednom zariadení nezhodí celý beh a zariadenie je `gps_pending` bez volania Google; Apple 401/403 → jedna obnova tokenu, potom `AppleAuthError` a žiadne ďalšie volania Google; strop `max_google_calls` sa dodrží; otváracie hodiny z Apple prežijú cez `enrich_venue` aj `enrich_all` (§8.9) |
| `export` | vytvorené tabuľky a index presne podľa §3.3; počty riadkov sedia; `venue_categories` a `opening_hours` sú prepojené správnymi `venue_id`; `gps_pending = 1` ⇔ `lat IS NULL` |

### 11.2 iOS (XCTest)

Príkaz: `cd frontend && xcodebuild test -scheme SportNav -destination 'platform=iOS Simulator,name=iPhone 16'`

| Oblasť | Testované prípady |
|---|---|
| `SQLiteVenueRepository` | načíta všetky zariadenia s GPS z fixture DB; zariadenia s `gps_pending = 1` vynechá; kategórie a otváracie hodiny sú namapované; neznámy slug sa ignoruje |
| `MapViewModel` | prázdny filter → všetky; filter kategórie; filter vzdialenosti (hraničné hodnoty 0,5 a 20 km); bez polohy → filter vzdialenosti sa neaplikuje |
| `NavigationService` | presný tvar URL pre všetky 3 aplikácie; `availableApps` s mockom `URLOpening` (iba Apple / Apple + Google / všetky tri) |

### 11.3 Manuálny checklist (simulátor alebo zariadenie)

- prvé spustenie → systémový dialóg polohy; po zamietnutí sa mapa zobrazí bez pádu
- piny sú farebne odlíšené a pri oddialení sa zhlukujú
- ťuknutie na pin → karta s názvom, kategóriou, vzdialenosťou a hodinami
- „Navigovať" → priame otvorenie (1 aplikácia) alebo action sheet (viac aplikácií)
- filter mení piny na mape; jazyk aplikácie sk/cs/en

---

## 12. Riziká

| Riziko | Dopad | Mitigácia |
|---|---|---|
| iOS build a testy (kroky 5–8) vyžadujú macOS + Xcode | na Windows sa nedajú overiť | kroky 5–8 spúšťať iba na macOS; backend (kroky 1–3) je multiplatformový |
| Apple Maps Server API nevracia otváracie hodiny alebo ich vracia v inom formáte | prázdne hodiny v aplikácii | pred krokom 9 uložiť reálnu odpoveď do `tests/fixtures/` a podľa nej doplniť `normalize_opening_hours`; UI zobrazí „nedostupné" |
| Nesprávny geocoding (prvý výsledok vyhľadávania nie je hľadané zariadenie) | pin na zlom mieste | `resultTypeFilter=Poi`; po kroku 9 ručne skontrolovať vzorku ~20 zariadení |
| Vysoký podiel `gps_pending` | menej zariadení na mape | `build_db.py` vypíše štatistiku; ak je podiel nad 10 %, doplniť ďalšie dotazy (iba adresa) v novej iterácii návrhu |
| Limity / poplatky Google Places | porušenie pravidla nulových nákladov | fallback iba pre zariadenia bez Apple výsledku a iba `fields=geometry`; pred krokom 9 skontrolovať free tier |
| Dáta zo `mapa.multisport.cz` sú prevažne české | málo zariadení na Slovensku | po kroku 9 overiť pokrytie SK; prípadný ďalší zdroj patrí do novej verzie návrhu (mimo scope) |
| Zmena štruktúry webu Multisport → scraper prestane fungovať | nedá sa vytvoriť nový import | dáta sú v aplikácii zabudované, výpadok scrapera ovplyvní iba ďalšiu verziu |
| Mapovanie názov kategórie → slug je ručné | zariadenia bez kategórie | test v kroku 1 + log neznámych kategórií v `build_db.py` |
| Únik API kľúčov | zneužitie kľúča | kľúče iba v `backend/.env` (v `.gitignore`), nikdy vo `frontend/` |
