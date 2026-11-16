# SportNav – Design Document


---

## 1. Prehľad projektu

SportNav je natívna iOS aplikácia pre držiteľov Multisport karty. Umožňuje nájsť najbližšie akceptované športovisko na mape, filtrovať zariadenia podľa typu aktivity a jedným ťuknutím otvoriť navigáciu v externej mapovej aplikácii.

**Platforma:** iOS 16+  
**Distribúcia:** iOS simulátor a vlastné zariadenie cez Xcode s bezplatným Apple ID (App Store vyžaduje platený Apple Developer Program, preto je mimo scope — viď §7)  
**Náklady:** 0 € — žiadne platené služby, registrácie, API kľúče ani platobné karty  
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
      └─ OpenStreetMap Nominatim (zadarmo, bez kľúča)
           ├─ 1. dotaz: názov + adresa → GPS + otváracie hodiny (OSM tag)
           └─ 2. dotaz: iba adresa     → GPS budovy (ak 1. nič nenašiel)
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

### 3.2 Enrich script – GPS a otváracie hodiny (OpenStreetMap Nominatim)

#### Pravidlo nulových nákladov
> Žiadne platené služby, žiadne registrácie, žiadne API kľúče ani platobné karty. Všetky volania sú jednorazové počas vývoja. Do SQLite sa uloží výsledok — v produkcii sa žiadne API nevolá.

#### Zdroj: OpenStreetMap Nominatim

Verejný geocoder OpenStreetMap (`GET https://nominatim.openstreetmap.org/search`) — zadarmo, bez registrácie a bez kľúča. Apple Maps Server API (vyžaduje platený Apple Developer Program) a Google Places API (vyžaduje platobnú kartu) sa **nepoužívajú**.

**Podmienky použitia (Nominatim Usage Policy) — povinné:**
- najviac **1 požiadavka za sekundu**, žiadne paralelné požiadavky
- identifikujúca hlavička `User-Agent: SportNav-data-import/1.0`; voliteľne parameter `email` (kontakt pre prevádzkovateľa) z premennej `NOMINATIM_EMAIL`
- import je jednorazový, výsledok sa uloží do SQLite (žiadne opakované hromadné dopyty)
- v aplikácii je uvedená atribúcia **„© OpenStreetMap contributors"** (dáta sú pod licenciou ODbL), viď §5.3

**Dva dotazy na zariadenie:**

| Fáza | `q` | Pri výsledku | `gps_source` |
|---|---|---|---|
| 1. POI | `"<title>, <street>, <city>"` | GPS + otváracie hodiny z `extratags.opening_hours` | `nominatim_poi` |
| 2. adresa (iba ak 1. vrátila `[]`) | `"<street>, <city>"` | iba GPS budovy, otváracie hodiny ostanú prázdne | `nominatim_address` |
| — (aj 2. vrátila `[]`) | — | `gps_pending = 1`, `lat`/`lon` = NULL | `NULL` |

Prázdne časti dotazu (chýbajúca ulica alebo mesto) sa vynechajú. Ak zariadenie nemá ulicu ani mesto, fáza 2 sa preskočí.

Spoločné parametre: `format=jsonv2`, `limit=1`, `extratags=1`, `countrycodes=cz,sk`, `accept-language=cs`.

```python
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SportNav-data-import/1.0"

async def nominatim_search(query: str, client: httpx.AsyncClient,
                           email: str | None = None) -> dict | None:
    params = {"q": query, "format": "jsonv2", "limit": 1, "extratags": 1,
              "countrycodes": "cz,sk", "accept-language": "cs"}
    if email:
        params["email"] = email
    resp = await client.get(NOMINATIM_URL, params=params,
                            headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else None
    # pozor: "lat" a "lon" sú v odpovedi Nominatimu reťazce → float()
```

**Ukážka odpovede (skrátená):**
```json
[{"lat": "50.3561", "lon": "15.9187", "name": "Legion Gym",
  "extratags": {"opening_hours": "Mo-Fr 06:00-22:00; Sa,Su 08:00-20:00"}}]
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
    gps_source  TEXT,              -- 'nominatim_poi' | 'nominatim_address' | NULL
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
| CI/CD | žiadne — testy sa spúšťajú lokálne (Xcode Cloud vyžaduje platený Apple Developer Program) |
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
- Atribúcia dát: na karte zariadenia je pod otváracími hodinami malý text **„Poloha a hodiny: © OpenStreetMap contributors"** (povinné podľa licencie ODbL, §3.2)

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
- Publikovanie v App Store a Xcode Cloud (vyžadujú platený Apple Developer Program)
- Akékoľvek platené API alebo API vyžadujúce kľúč či platobnú kartu (Apple Maps Server API, Google Places API)

---

## 8. Spresnenia návrhu

Rozhodnutia, ktoré dopĺňajú alebo spresňujú sekcie 3–6. Pri rozpore platí táto sekcia.

1. **Zariadenia bez GPS** — `lat`/`lon` sú v SQLite `NULL` a `gps_pending = 1`. `VenueRepository` načítava iba záznamy s `gps_pending = 0`, preto `Venue.coordinate` ostáva neoptional.
2. **Kategórie** — scraper vracia názvy kategórií (napr. `"Posilovny a silové tréninky"`), nie slugy. Backend obsahuje statickú mapu *názov → slug* pre 7 kategórií z `VenueCategory` (§6). Tabuľka `categories` sa naplní práve týmito 7 riadkami. Neznáma kategória sa zaloguje a preskočí, zariadenie sa však uloží.
3. **Žiadne kľúče** — pipeline nepotrebuje žiadny kľúč ani token. Jediná voliteľná premenná je `NOMINATIM_EMAIL` (kontaktný e-mail posielaný Nominatimu podľa usage policy). Načítava sa z prostredia alebo z `backend/.env`; ak chýba, parameter `email` sa neposiela. E-mail sa nikdy nevypisuje do logov.
4. **Rýchlosť a poradie** — `enrich_all` spracúva zariadenia **sekvenčne** (žiadna súbežnosť) a zachováva ich poradie. Medzi začiatkami dvoch po sebe idúcich požiadaviek na Nominatim v rámci jedného behu `enrich_all` uplynie aspoň `min_interval` sekúnd (predvolene `1.0`; testy používajú `0` alebo malú hodnotu). Platí to aj pre dve požiadavky toho istého zariadenia (fáza 1 a 2).
5. **Otváracie hodiny** — `normalize_opening_hours(raw)` prevedie hodnotu OSM tagu `opening_hours` (reťazec) na zoznam `(day, opens, closes)` s `day ∈ {mon,…,sun}` a časom `HH:MM`, zoradený podľa dňa (po → ne) a času otvorenia. Funkcia nikdy nevyhodí výnimku. Podporovaná podmnožina syntaxe OSM:
   - `24/7` → všetkých 7 dní `00:00–23:59`
   - pravidlá oddelené `;`; pravidlo = `[výber dní] časy` alebo `[výber dní] off` / `closed`
   - výber dní: dni `Mo Tu We Th Fr Sa Su`, rozsahy (`Mo-Fr`, aj cez koniec týždňa `Sa-Mo`) a zoznamy (`Mo,We,Fr-Su`); bez výberu dní platí pravidlo pre všetky dni
   - časy: jeden alebo viac rozsahov `HH:MM-HH:MM` oddelených čiarkou; `24:00` ako čas zatvorenia sa zapíše ako `23:59`; `closes < opens` znamená prevádzku cez polnoc (§8.10)
   - neskoršie pravidlo **nahrádza** skoršie pre dni, ktoré vyberá (sémantika OSM); `off` / `closed` tieto dni vyprázdni
   - čokoľvek iné (sviatky `PH`/`SH`, mesiace, týždne, `sunrise`/`sunset`, komentáre v úvodzovkách, `+`, `||`, čas nad `24:00`, pravidlá oddelené čiarkou, …) → celý výsledok je `[]` (všetko alebo nič)
   - `None`, iný typ ako reťazec alebo prázdny reťazec → `[]`

   V aplikácii sa zobrazujú dnešné hodiny, prípadne text „Otváracie hodiny nedostupné".
6. **Mapa** — SwiftUI `Map` na iOS 16 nepodporuje clustering, preto je mapa implementovaná ako `UIViewRepresentable` nad `MKMapView`: `MKMarkerAnnotationView` s `clusteringIdentifier` a `userTrackingMode = .followWithHeading` pre smer pohľadu. Smer sa berie z `CLLocationManager` heading, `CMMotionManager` sa nepoužije.
7. **Filter** — prázdny výber kategórií znamená „všetky". Predvolená vzdialenosť je 5 km, rozsah 0,5–20 km (krok 0,5 km). Vzdialenosť sa počíta cez `CLLocation.distance(from:)`. Ak používateľ nepovolí polohu, mapa sa vycentruje na oblasť všetkých zariadení a filter vzdialenosti sa vypne.
8. **Xcode projekt** — vytvára ho človek ručne v Xcode 16+ (viď §10, krok 4). Používa *synchronized folders*, takže nové `.swift` súbory v `frontend/SportNav/` sa do projektu pridávajú automaticky a agenti nemusia upravovať `project.pbxproj`.
9. **Chyby Nominatimu** — „Nominatim nič nenašiel" znamená **HTTP 200 s prázdnym JSON poľom `[]`**. Iba vtedy sa pokračuje ďalšou fázou (§3.2).
   - **HTTP 403** (IP zablokovaná za porušenie usage policy) → `NominatimBlockedError`; **celý beh sa okamžite ukončí** a už sa neposiela žiadna ďalšia požiadavka. `build_db.py` vypíše chybu a skončí s kódom 1 bez zápisu databázy.
   - **429, iné 4xx/5xx, timeout, chyba spojenia, nevalidný JSON alebo JSON, ktorý nie je pole** → toto zariadenie sa označí `gps_pending = 1` **bez ďalšej fázy**, chyba sa zaloguje a beh pokračuje ďalším zariadením.
   - Výsledok bez platných súradníc (`lat`/`lon` chýba, nedá sa previesť na `float` alebo je mimo rozsahu ±90 / ±180) sa posudzuje ako prázdny výsledok danej fázy.
   - Výnimky httpx sa logujú iba typom a HTTP kódom (bez URL), aby sa do logu nedostal `NOMINATIM_EMAIL`.
10. **Zápis otváracích hodín v SQLite** (spresňuje §8.5, platí pre backend aj iOS) — jeden riadok `(day, opens, closes)` popisuje jeden blok otvorenia, ktorý **začína v deň `day`**. Ak je `closes < opens`, prevádzka končí po polnoci **nasledujúceho dňa** (napr. `fri 22:00–02:00` = piatok 22:00 až sobota 02:00). Nonstop prevádzka je 7 riadkov `00:00–23:59`. V jeden deň môže byť viac riadkov (prestávka). Viacdňové súvislé obdobia sa nezapisujú. iOS pri „dnešných hodinách" zobrazí riadky pre dnešný deň a pri `closes < opens` bez ďalšej úpravy zobrazí rozsah `opens–closes`. Stav „otvorené teraz" MVP nepočíta.
11. **`street` a `city` v Swifte** (spresňuje §6 vs. §3.3) — SQLite môže obsahovať NULL (exportér ukladá prázdne reťazce ako NULL). `Venue.street` a `Venue.city` ostávajú neoptional `String`; `SQLiteVenueRepository` mapuje NULL na `""` a UI prázdne hodnoty nezobrazí.

---

## 9. Dotknuté súbory a moduly

### 9.1 Backend — dátový pipeline (Python 3.11+, iba dev)

```
backend/
├── requirements.txt              # httpx, pytest
├── .env.example                  # NOMINATIM_EMAIL=   (voliteľné, §8.3)
├── data/
│   └── venues_raw.json           # export z Apify Actora (ukladá človek v kroku 9)
├── sportnav_data/
│   ├── __init__.py
│   ├── categories.py             # CATEGORY_SLUGS: dict[názov, slug], CATEGORIES: list[(slug, name)]
│   ├── opening_hours.py          # normalize_opening_hours(raw) -> list[tuple[str, str, str]] (OSM syntax, §8.5)
│   ├── enrich.py                 # nominatim_search, enrich_venue, enrich_all, NominatimBlockedError
│   └── export.py                 # create_schema(conn), export_venues(venues, path)
├── scripts/
│   ├── build_db.py               # CLI: --input data/venues_raw.json --output <cesta>.sqlite
│   └── make_test_fixture.py      # vytvorí frontend/SportNavTests/Fixtures/test_venues.sqlite
└── tests/
    ├── fixtures/                 # vzorové odpovede Nominatim (nominatim_*.json)
    ├── test_categories.py
    ├── test_opening_hours.py
    ├── test_enrich.py
    └── test_export.py
```

Koreňový `.gitignore`: `backend/.env`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.DS_Store`, `xcuserdata/`, `DerivedData/`.

**Rozhrania (Python):**

```python
class NominatimBlockedError(Exception)                          # HTTP 403, ukončí beh (§8.9)
async def nominatim_search(query: str, client: httpx.AsyncClient,
                           email: str | None = None) -> dict | None   # prvý výsledok alebo None pri []
async def enrich_venue(venue: dict, client: httpx.AsyncClient, email: str | None = None,
                       min_interval: float = 1.0) -> dict         # POI → adresa → gps_pending (§3.2)
async def enrich_all(venues: list[dict], client: httpx.AsyncClient, email: str | None = None,
                     min_interval: float = 1.0) -> list[dict]     # sekvenčne, poradie zachované (§8.4)
def normalize_opening_hours(raw: object) -> list[tuple[str, str, str]]   # OSM syntax (§8.5)
def create_schema(conn: sqlite3.Connection) -> None          # schéma §3.3
def export_venues(venues: list[dict], path: str) -> None     # vytvorí schému a zapíše dáta
```

`httpx.AsyncClient` sa do funkcií odovzdáva parametrom, aby sa dal v testoch nahradiť cez `httpx.MockTransport`. Obohatený záznam má navyše kľúče `lat`, `lon` (`float` alebo `None`), `opening_hours` (normalizovaný zoznam), `gps_source` (`nominatim_poi` | `nominatim_address` | `None`) a `gps_pending` (0/1). Vstupný záznam sa nemení (funkcie vracajú kópiu).

`build_db.py` (CLI): nevyžaduje žiadnu premennú prostredia; voliteľne načíta `NOMINATIM_EMAIL` (z prostredia alebo `backend/.env`). Pred prvou požiadavkou overí zapisovateľnosť výstupu. Po dokončení vypíše štatistiku: počet záznamov, počet a podiel `gps_pending`, počty podľa `gps_source`, počet zariadení bez kategórie, počty podľa kategórie a varovanie pri podiele `gps_pending` nad 10 % (§12). Pri `NominatimBlockedError` skončí s kódom 1 bez zápisu databázy.

`make_test_fixture.py` a `frontend/SportNavTests/Fixtures/test_venues.sqlite` sa pri prechode na Nominatim **nemenia** (hodnoty `gps_source` vo fixture sú iba informatívne, iOS ich nečíta). Zmena by zbytočne kolidovala s rozpracovaným krokom 5.

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
| 2 | **Enrich** — `enrich.py`: Nominatim (POI → adresa → `gps_pending`), sekvenčný `enrich_all` s `min_interval` + testy s `httpx.MockTransport` | agent | `enrich.py` | `pytest` (bez reálnej siete) |
| 3 | **Export + CLI** — `export.py` (schéma presne podľa §3.3), `scripts/build_db.py`, testovacia fixture DB `frontend/SportNavTests/Fixtures/test_venues.sqlite` + testy | agent | `export.py`, `build_db.py`, fixture DB | `pytest` |
| 3a | **Prechod na Nominatim** (refaktor už implementovaných krokov 1–3; pôvodne Apple Maps + Google Places) — prepísať `sportnav_data/enrich.py` (§3.2, §8.3, §8.4, §8.9, §9.1), `sportnav_data/opening_hours.py` (OSM syntax, §8.5), `scripts/build_db.py` (§9.1), `.env.example`, `backend/README.md`; nahradiť testy `tests/test_enrich.py`, `tests/test_opening_hours.py` a časť `# --- build_db CLI` v `tests/test_export.py` (§11.1); odstrániť fixtures `apple_*.json` / `google_*.json` a pridať `nominatim_*.json`. Vo zvyšku `tests/test_export.py` (testy exportu) sa smú zmeniť iba vzorové hodnoty `gps_source` (`apple_maps` → `nominatim_poi`). **Nemeniť:** `categories.py`, `export.py`, schému §3.3, `make_test_fixture.py`, fixture DB ani nič vo `frontend/`. Mimo `make_test_fixture.py` (jeho hodnoty `gps_source` sú historické a informatívne, §9.1) nesmie v `backend/` ostať žiadna zmienka o Apple Maps Server API, Google Places, `APPLE_MAPS_AUTH_TOKEN` ani `GOOGLE_API_KEY`. | agent | §9.1 | `pytest` |
| 4 | **Xcode projekt** — Xcode 16+ → iOS App, SwiftUI, názov `SportNav`, uložiť do `frontend/`, deployment target iOS 16, unit test target `SportNavTests`, SPM balík `SQLite.swift`. Commitnúť. | **človek (macOS)** | `frontend/SportNav.xcodeproj` | projekt sa zbuildí v Xcode |
| 5 | **Modely + Repository** — `Venue.swift`, `VenueCategory.swift` (displayName, color, SF Symbol ikona), `VenueRepository.swift` + testy nad fixture DB | agent (macOS) | §9.2 Models, Data | `xcodebuild test` |
| 6 | **Služby** — `LocationService.swift`, `NavigationService.swift` (§5.4, §8.6) + testy NavigationService | agent (macOS) | §9.2 Services | `xcodebuild test` |
| 7 | **ViewModel** — `FilterState`, `MapViewModel` (filter podľa kategórie a vzdialenosti, §8.7) + testy | agent (macOS) | §9.2 ViewModels | `xcodebuild test` |
| 8 | **UI** — `MapScreen`, `VenueMapView` (clustering, heading, farby pinov), `FilterSheet`, `VenueCardSheet` (vrátane OSM atribúcie, §5.3), `Info.plist` (§4.3), `Localizable.xcstrings` (sk/cs/en) | agent (macOS) | §9.2 Views, Resources | `xcodebuild build` + manuálny checklist §11.3 |
| 9 | **Reálne dáta** — spustiť Apify Actor v bezplatnom účte Apify (webová konzola, bez tokenu), uložiť `backend/data/venues_raw.json`, spustiť `cd backend && python scripts/build_db.py --input data/venues_raw.json --output ../frontend/SportNav/Resources/venues.sqlite` (beží ~2 s na zariadenie kvôli limitu 1 požiadavka/s) | **človek** | `venues.sqlite` v bundli | počet záznamov, podiel `gps_pending` (§12) |

Kroky 1–3 a 3a sa dajú robiť na Windows aj macOS. Kroky 5–8 vyžadujú macOS s Xcode.

---

## 11. Testovacia stratégia

### 11.1 Backend (pytest)

Príkaz: `cd backend && python -m pytest -q`

Testy nesmú volať reálnu sieť. HTTP sa simuluje cez `httpx.MockTransport` s fixtures v `tests/fixtures/`.

| Oblasť | Testované prípady |
|---|---|
| `categories` | všetkých 7 názvov → správny slug; neznámy názov → preskočený (log), zariadenie ostáva |
| `opening_hours` | `"Mo-Fr 06:00-22:00; Sa,Su 08:00-20:00"` → 7 riadkov; `"24/7"`; viac rozsahov v jeden deň (`"Mo-Su 10:00-14:00,16:00-22:00"`); cez polnoc (`"Fr 22:00-02:00"` → `("fri", "22:00", "02:00")`); `24:00` → `23:59`; rozsah cez koniec týždňa (`"Sa-Mo …"`); pravidlo bez dní; neskoršie pravidlo prepíše skoršie a `off` vyprázdni deň (`"Mo-Fr 08:00-20:00; We off"`); nepodporovaná syntax (`"Mo-Fr 08:00-17:00; PH off"`, `"sunrise-sunset"`, čiarkou oddelené pravidlá) → `[]`; `None` / číslo / `""` → `[]` bez výnimky |
| `enrich` | POI výsledok → `gps_source = "nominatim_poi"`, `lat`/`lon` ako `float`, hodiny z `extratags.opening_hours`; POI `[]` → adresný dotaz → `nominatim_address` bez hodín (aj keď adresný výsledok má `extratags.opening_hours`); oba `[]` → `gps_pending = 1`, `lat/lon = None`; chýbajúca ulica aj mesto → bez adresného dotazu; overenie odoslaných parametrov (`q`, `format=jsonv2`, `limit=1`, `extratags=1`, `countrycodes=cz,sk`) a hlavičky `User-Agent`; `email` sa posiela iba ak je zadaný; 429 / 5xx / timeout / nevalidný JSON / JSON, ktorý nie je pole → `gps_pending` bez adresného dotazu a beh pokračuje; neplatné súradnice → prázdny výsledok fázy; 403 → `NominatimBlockedError` a žiadne ďalšie požiadavky; poradie výsledkov `enrich_all` = poradie vstupu; žiadne súbežné požiadavky a odstup ≥ `min_interval` medzi požiadavkami (meraný v teste s malým `min_interval`); vstupný záznam sa nezmení |
| `build_db` | beh bez akejkoľvek premennej prostredia; `NOMINATIM_EMAIL` z `.env` sa použije a nevypíše; štatistika vrátane počtov podľa `gps_source`; `NominatimBlockedError` → kód 1 a výstupný súbor sa nevytvorí; nezapisovateľný výstup → chyba pred prvou požiadavkou |
| `export` | vytvorené tabuľky a index presne podľa §3.3; počty riadkov sedia; `venue_categories` a `opening_hours` sú prepojené správnymi `venue_id`; `gps_pending = 1` ⇔ `lat IS NULL` |

### 11.2 iOS (XCTest)

Príkaz: `cd frontend && xcodebuild test -scheme SportNav -destination 'platform=iOS Simulator,name=iPhone 16'`

| Oblasť | Testované prípady |
|---|---|
| `SQLiteVenueRepository` | načíta všetky zariadenia s GPS z fixture DB; zariadenia s `gps_pending = 1` vynechá; kategórie a otváracie hodiny sú namapované (vrátane `closes < opens`, §8.10); NULL `street`/`city` sa namapuje na `""` (§8.11); zariadenia 8 a 9 z fixture DB (neznáma kategória, §8.2) sa načítajú s prázdnymi, resp. zníženými kategóriami |
| `MapViewModel` | prázdny filter → všetky; filter kategórie; filter vzdialenosti (hraničné hodnoty 0,5 a 20 km); bez polohy → filter vzdialenosti sa neaplikuje |
| `NavigationService` | presný tvar URL pre všetky 3 aplikácie; `availableApps` s mockom `URLOpening` (iba Apple / Apple + Google / všetky tri) |

### 11.3 Manuálny checklist (simulátor alebo zariadenie)

- prvé spustenie → systémový dialóg polohy; po zamietnutí sa mapa zobrazí bez pádu
- piny sú farebne odlíšené a pri oddialení sa zhlukujú
- ťuknutie na pin → karta s názvom, kategóriou, vzdialenosťou, hodinami a atribúciou „© OpenStreetMap contributors"
- „Navigovať" → priame otvorenie (1 aplikácia) alebo action sheet (viac aplikácií)
- filter mení piny na mape; jazyk aplikácie sk/cs/en

---

## 12. Riziká

| Riziko | Dopad | Mitigácia |
|---|---|---|
| iOS build a testy (kroky 5–8) vyžadujú macOS + Xcode | na Windows sa nedajú overiť | kroky 5–8 spúšťať iba na macOS; backend (kroky 1–3) je multiplatformový |
| OSM má otváracie hodiny iba pri časti zariadení, alebo v nepodporovanej syntaxi | prázdne hodiny v aplikácii | UI zobrazí „Otváracie hodiny nedostupné"; podporovaná podmnožina syntaxe (§8.5) pokrýva bežné zápisy; rozšírenie parsera je samostatná iterácia návrhu |
| Nominatim nenájde zariadenie podľa názvu (POI v OSM chýba alebo má iný názov) | pin na adrese budovy namiesto presného miesta | adresný dotaz (fáza 2) — pin je aspoň na správnej budove; `gps_source = nominatim_address` umožní tieto prípady spočítať |
| Nesprávny geocoding (prvý výsledok nie je hľadané zariadenie) | pin na zlom mieste | `countrycodes=cz,sk`; po kroku 9 ručne skontrolovať vzorku ~20 zariadení |
| Vysoký podiel `gps_pending` | menej zariadení na mape | `build_db.py` vypíše štatistiku; ak je podiel nad 10 %, ďalšie stratégie dotazov patria do novej iterácie návrhu |
| Porušenie usage policy Nominatimu (príliš rýchle požiadavky) → zablokovanie IP (HTTP 403) | import sa nedokončí | sekvenčné požiadavky s odstupom ≥ 1 s, `User-Agent`, okamžité ukončenie pri 403 (§8.9); import spúšťať iba raz |
| Licencia ODbL — databáza obsahuje dáta z OSM | povinnosť atribúcie | text „© OpenStreetMap contributors" na karte zariadenia (§5.3); pri verejnom šírení `venues.sqlite` platí aj share-alike ODbL |
| Dlhý beh importu (limit 1 požiadavka/s, až 2 dotazy na zariadenie) | pri ~3 000 zariadeniach 1–2 hodiny | jednorazový import (krok 9); priebeh sa loguje |
| Dáta zo `mapa.multisport.cz` sú prevažne české | málo zariadení na Slovensku | po kroku 9 overiť pokrytie SK; prípadný ďalší zdroj patrí do novej verzie návrhu (mimo scope) |
| Zmena štruktúry webu Multisport → scraper prestane fungovať | nedá sa vytvoriť nový import | dáta sú v aplikácii zabudované, výpadok scrapera ovplyvní iba ďalšiu verziu |
| Mapovanie názov kategórie → slug je ručné | zariadenia bez kategórie | test v kroku 1 + log neznámych kategórií v `build_db.py` |
| Únik kontaktného e-mailu (`NOMINATIM_EMAIL`) | e-mail v gite alebo logoch | iba v `backend/.env` (v `.gitignore`), nikdy sa nelogovať (§8.9) |
