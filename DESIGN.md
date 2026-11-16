# SportNav – Design Document


---

## 1. Prehľad projektu

SportNav je natívna Android aplikácia pre držiteľov Multisport karty. Umožňuje nájsť najbližšie akceptované športovisko na mape, filtrovať zariadenia podľa typu aktivity a jedným ťuknutím otvoriť navigáciu v externej mapovej aplikácii.

**Platforma:** Android 8.0+ (API 26)  
**Distribúcia:** APK nainštalovaný cez Android Studio do emulátora alebo vlastného telefónu — zadarmo, bez účtu (Google Play vyžaduje jednorazový poplatok, preto je mimo scope — viď §7)  
**Náklady:** 0 € — žiadne platené služby, registrácie, API kľúče ani platobné karty  
**Jazyk rozhrania:** SK, CZ, EN  
**Backend:** žiadny — dáta o zariadeniach sú offline v lokálnej SQLite databáze zabudovanej v aplikácii; internet je potrebný iba na mapové dlaždice (§8.6)

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

[PRODUKCIA – Android aplikácia]
venues.sqlite (v assets aplikácie, offline)
  → SQLite reader
  → MapLibre Native (dlaždice OpenFreeMap, online) + LocationManager
  → UI (Jetpack Compose)
  → Intent → Google Maps / Waze / iná mapová aplikácia
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

Výstupom enrich scriptu je `venues.sqlite` zabudovaný priamo do aplikácie (Android `assets/`, §8.12).

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

## 4. Android aplikácia

### 4.1 Architektúra

Aplikácia používa **MVVM** — jednoduchú dvojvrstvovú štruktúru bez zbytočnej komplexnosti:

```
UI (Jetpack Compose)
  └─ ViewModel (androidx.lifecycle.ViewModel + StateFlow)
       └─ Repository (SQLite reader) + LocationService (LocationManager)
```

Žiadny networking layer, žiadny remote API klient, žiadna autentifikácia. Jediná sieťová komunikácia sú mapové dlaždice, ktoré si MapLibre sťahuje sám (§8.6); dáta o zariadeniach sú vždy lokálne.

### 4.2 Technologický stack

| Vrstva | Technológia |
|---|---|
| Jazyk | Kotlin (verzia zo šablóny Android Studio) |
| Platforma | minSdk 26 (Android 8.0); compileSdk / targetSdk podľa šablóny Android Studio |
| UI | Jetpack Compose + Material 3 |
| Mapy | MapLibre Native Android (`org.maplibre.gl:android-sdk`) — open source, bez kľúča |
| Mapové dlaždice | OpenFreeMap, štýl `https://tiles.openfreemap.org/styles/liberty` — zadarmo, bez registrácie a kľúča, bez limitu požiadaviek, komerčné použitie povolené |
| Poloha & smer | `android.location.LocationManager` (bez Google Play Services); modrá bodka a šípka smeru cez MapLibre `LocationComponent` |
| Lokálna DB | framework `android.database.sqlite.SQLiteDatabase` (bez Room — schéma §3.3 je daná backendom) |
| Stav / async | `ViewModel`, `StateFlow`, Kotlin coroutines |
| Navigácia (externá) | Android `Intent` — `google.navigation:`, `https://waze.com/ul`, `geo:` |
| Testy | JUnit 4, Robolectric (SQLite na JVM), `kotlinx-coroutines-test` |
| Build | Gradle (Kotlin DSL) cez `gradlew` |
| CI/CD | žiadne — testy sa spúšťajú lokálne |
| Verziovanie | Git + GitHub |

Google Maps SDK sa **nepoužíva** — vyžaduje API kľúč v Google Cloud (pravidlo nulových nákladov, §3.2).

### 4.3 Oprávnenia a manifest (`AndroidManifest.xml`)

| Položka | Dôvod |
|---|---|
| `android.permission.INTERNET` | sťahovanie mapových dlaždíc (bez dialógu) |
| `ACCESS_FINE_LOCATION` + `ACCESS_COARSE_LOCATION` | poloha na mape a výpočet vzdialenosti; runtime dialóg pri prvom spustení; stačí aj „približná poloha" (§8.14) |
| `<queries>`: `<package>` `com.google.android.apps.maps` a `com.waze` + `<intent>` `ACTION_VIEW` so schémou `geo` | od Androidu 11 nutné, aby aplikácia videla nainštalované mapové aplikácie (§5.4); nie je to oprávnenie, žiadny dialóg |

Žiadne ďalšie oprávnenia nie sú potrebné. Kamera, mikrofón, fotky, notifikácie — nie sú súčasťou scope.

---

## 5. Obrazovky a tok

### 5.1 Obrazovky

| Obrazovka | Popis |
|---|---|
| **Mapa (Home)** | Hlavná obrazovka — interaktívna mapa s pinmi, geolocate button, tlačidlo filtra |
| **Filter sheet** | Výber kategórie (checklist), slider vzdialenosti (0,5–20 km) |
| **Karta zariadenia** | Bottom sheet (`ModalBottomSheet`) po ťuknutí na pin — názov, kategória, vzdialenosť, dnešné hodiny, tlačidlo „Navigovať" |

### 5.2 Navigačný tok

```
Spustenie aplikácie
  └─ Povolenie polohy (systémový dialóg Androidu, pri prvom spustení)
       └─ Mapa (Home) – piny v okolí
            ├─ Ťuknutie na pin → Karta zariadenia
            │    └─ „Navigovať" → výber aplikácie (Google Maps / Waze / Iná mapová aplikácia)
            │         └─ Otvorenie externej mapy s cieľom
            ├─ Ťuknutie na zhluk → priblíženie mapy
            └─ Tlačidlo filtra → Filter sheet
                 └─ Výber kategórie / vzdialenosti → Mapa (aktualizovaná)
```

### 5.3 Mapa – detaily

- MapLibre Native so štýlom OpenFreeMap Liberty (§8.6)
- Centrovaná na aktuálnu GPS polohu (bez povolenia polohy na oblasť všetkých zariadení, §8.7)
- Modrá bodka = aktuálna poloha + šípka smeru podľa kompasu zariadenia (MapLibre `LocationComponent`, `RenderMode.COMPASS`)
- Piny (farebné krúžky) podľa hlavnej kategórie zariadenia (§8.13)
- Pri oddialení sa piny zhlukujú (clustering) — krúžok s počtom zariadení; ťuknutie naň mapu priblíži
- Atribúcia mapy: MapLibre automaticky zobrazí atribúciu zo štýlu (OpenFreeMap, OpenMapTiles, © OpenStreetMap contributors) — nesmie sa skryť
- Atribúcia dát: na karte zariadenia je pod otváracími hodinami malý text **„Poloha a hodiny: © OpenStreetMap contributors"** (povinné podľa licencie ODbL, §3.2)

### 5.4 Navigácia (externá)

Po ťuknutí na „Navigovať" aplikácia:
1. Zistí dostupné možnosti cez `PackageManager` (vyžaduje `<queries>`, §4.3), v tomto poradí:
   - **Google Maps** — ak je nainštalovaný balík `com.google.android.apps.maps`
   - **Waze** — ak je nainštalovaný balík `com.waze`
   - **Iná mapová aplikácia** — ak `geo:` URI vie otvoriť aspoň jedna aplikácia **okrem** dvoch vyššie (napr. Mapy.cz, OsmAnd)
2. Ak nie je dostupná žiadna → zobrazí hlášku „Nie je nainštalovaná žiadna mapová aplikácia" (bez pádu)
3. Ak je dostupná iba jedna → otvorí ju priamo
4. Ak je viac možností → zobrazí dialóg so zoznamom dostupných aplikácií
5. Spustenie intentu je obalené zachytením `ActivityNotFoundException` (napr. Google Maps je nainštalovaný, ale vypnutý) → rovnaká hláška ako v bode 2, bez pádu

```
// Ciele navigácie (súradnice vždy s desatinnou bodkou — Locale.ROOT, 6 desatinných miest)
GOOGLE_MAPS → "google.navigation:q=<lat>,<lon>"                        balík com.google.android.apps.maps
WAZE        → "https://waze.com/ul?ll=<lat>,<lon>&navigate=yes"        balík com.waze
OTHER_GEO   → "geo:<lat>,<lon>?q=<lat>,<lon>(<názov, URL-enkódovaný>)" bez balíka (výber nechá na systéme)
```

---

## 6. Dátový model (Kotlin)

```kotlin
data class Venue(
    val id: Int,
    val name: String,
    val street: String,
    val city: String,
    val latitude: Double,
    val longitude: Double,
    val categories: List<VenueCategory>,
    val openingHours: List<DaySchedule>,
    val phone: String?,
    val website: String?,
)

// Poradie konštánt určuje hlavnú kategóriu zariadenia (§8.13)
enum class VenueCategory(val slug: String, val colorHex: String) {
    FITNESS ("posilovny-a-silove-treninky-5", "#E53935"),
    POOL    ("bazeny-a-vodni-sporty-1",       "#1E88E5"),
    YOGA    ("joga-a-zdravotni-cviceni-3",    "#8E24AA"),
    CLIMBING("lezecke-steny-4",               "#6D4C41"),
    RACKET  ("raketove-a-micove-sporty-7",    "#43A047"),
    GROUP   ("skupinove-a-tanecni-lekce-9",   "#FB8C00"),
    WELLNESS("wellness-a-relax-10",           "#00ACC1");

    companion object {
        fun fromSlug(slug: String): VenueCategory?   // neznámy slug → null
    }
}
// Lokalizovaný názov a ikona sú v UI vrstve: VenueCategory.labelRes(), VenueCategory.icon()

enum class Weekday(val code: String) { MON("mon"), TUE("tue"), WED("wed"), THU("thu"), FRI("fri"), SAT("sat"), SUN("sun") }

data class DaySchedule(
    val day: Weekday,
    val opens: String,   // "06:00"
    val closes: String,  // "22:00"
)

data class GeoPoint(val latitude: Double, val longitude: Double)
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
- Wear OS / smart-hodinky aplikácia
- iOS verzia aplikácie
- Aktualizácia dát po vydaní aplikácie (nová verzia = nový import SQLite)
- Publikovanie v Google Play (jednorazový registračný poplatok)
- Offline mapové dlaždice — mapa vyžaduje internet; dáta o zariadeniach sú offline
- Akékoľvek platené API alebo API vyžadujúce kľúč či platobnú kartu (Apple Maps Server API, Google Places API, Google Maps SDK)

---

## 8. Spresnenia návrhu

Rozhodnutia, ktoré dopĺňajú alebo spresňujú sekcie 3–6. Pri rozpore platí táto sekcia.

1. **Zariadenia bez GPS** — `lat`/`lon` sú v SQLite `NULL` a `gps_pending = 1`. `VenueRepository` načítava iba záznamy s `gps_pending = 0`, preto `Venue.latitude` a `Venue.longitude` sú nenulové `Double`.
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
6. **Mapa (MapLibre + OpenFreeMap)** — `VenueMapView` je `AndroidView` nad MapLibre `MapView`:
   - `MapLibre.getInstance(context)` sa zavolá pred vytvorením `MapView`; životný cyklus `MapView` (`onStart`, `onResume`, `onPause`, `onStop`, `onDestroy`) sa preposiela z Compose lifecycle (`LifecycleEventObserver`).
   - Štýl: `https://tiles.openfreemap.org/styles/liberty` — jediná konštanta v kóde. Žiadny API kľúč, žiadny `User-Agent` navyše netreba (MapLibre posiela vlastný).
   - Zariadenia sú jeden `GeoJsonSource` s `cluster = true`, `clusterRadius = 50`, `clusterMaxZoom = 14`. Každý bod má vlastnosti `id` (číslo) a `color` (hex z §8.13).
   - Vrstvy: zhluky = `CircleLayer` (filter `has("point_count")`) + `SymbolLayer` s počtom (`point_count_abbreviated`, písmo, ktoré obsahuje štýl Liberty); samostatné body = `CircleLayer` s farbou z vlastnosti `color`.
   - Ťuknutie: `queryRenderedFeatures` na vrstvách zhlukov a bodov; zhluk → kamera sa priblíži o 2 úrovne na jeho stred; bod → `MapViewModel.selectVenue(id)`.
   - Pri zmene `visibleVenues` sa iba aktualizujú dáta zdroja (`setGeoJson`), mapa sa znova nevytvára.
   - Poloha: `LocationComponent` sa aktivuje iba pri udelenom povolení, s predvoleným `LocationEngine` MapLibre (bez Google Play Services), `RenderMode.COMPASS`, `CameraMode.NONE`. Tlačidlo „moja poloha" presunie kameru na poslednú známu polohu (zoom 13).
   - Bez internetu sa dlaždice nenačítajú, ale aplikácia nesmie spadnúť; piny, karta zariadenia aj navigácia fungujú ďalej.
7. **Filter** — prázdny výber kategórií znamená „všetky"; zariadenie vyhovuje, ak má **aspoň jednu** z vybraných kategórií. Predvolená vzdialenosť je 5 km, rozsah 0,5–20 km (krok 0,5 km). Vzdialenosť sa počíta funkciou `distanceMeters(a, b)` (Haversine, polomer Zeme 6 371 000 m). Ak používateľ nepovolí polohu, mapa sa vycentruje na oblasť všetkých zariadení a filter vzdialenosti sa vypne.
8. **Android Studio projekt** — vytvára ho človek ručne v Android Studio (viď §10, krok 4), aby vznikol Gradle wrapper a nainštalovalo sa Android SDK. Agenti potom upravujú iba textové súbory projektu (`*.kt`, `*.kts`, `libs.versions.toml`, manifest, `res/`).
9. **Chyby Nominatimu** — „Nominatim nič nenašiel" znamená **HTTP 200 s prázdnym JSON poľom `[]`**. Iba vtedy sa pokračuje ďalšou fázou (§3.2).
   - **HTTP 403** (IP zablokovaná za porušenie usage policy) → `NominatimBlockedError`; **celý beh sa okamžite ukončí** a už sa neposiela žiadna ďalšia požiadavka. `build_db.py` vypíše chybu a skončí s kódom 1 bez zápisu databázy.
   - **429, iné 4xx/5xx, timeout, chyba spojenia, nevalidný JSON alebo JSON, ktorý nie je pole** → toto zariadenie sa označí `gps_pending = 1` **bez ďalšej fázy**, chyba sa zaloguje a beh pokračuje ďalším zariadením.
   - Výsledok bez platných súradníc (`lat`/`lon` chýba, nedá sa previesť na `float` alebo je mimo rozsahu ±90 / ±180) sa posudzuje ako prázdny výsledok danej fázy.
   - Výnimky httpx sa logujú iba typom a HTTP kódom (bez URL), aby sa do logu nedostal `NOMINATIM_EMAIL`.
10. **Zápis otváracích hodín v SQLite** (spresňuje §8.5, platí pre backend aj Android) — jeden riadok `(day, opens, closes)` popisuje jeden blok otvorenia, ktorý **začína v deň `day`**. Ak je `closes < opens`, prevádzka končí po polnoci **nasledujúceho dňa** (napr. `fri 22:00–02:00` = piatok 22:00 až sobota 02:00). Nonstop prevádzka je 7 riadkov `00:00–23:59`. V jeden deň môže byť viac riadkov (prestávka). Viacdňové súvislé obdobia sa nezapisujú. Aplikácia pri „dnešných hodinách" (`todaySchedule`, dnešný deň z `java.time.LocalDate.now().dayOfWeek`) zobrazí riadky pre dnešný deň a pri `closes < opens` bez ďalšej úpravy zobrazí rozsah `opens–closes`. Stav „otvorené teraz" MVP nepočíta.
11. **`street` a `city` v Kotline** (spresňuje §6 vs. §3.3) — SQLite môže obsahovať NULL (exportér ukladá prázdne reťazce ako NULL). `Venue.street` a `Venue.city` ostávajú nenulové `String`; `SQLiteVenueRepository` mapuje NULL na `""` a UI prázdne hodnoty nezobrazí. Neznámy slug kategórie (`VenueCategory.fromSlug` vráti `null`) sa vynechá.
12. **Zabudovaná databáza** — `venues.sqlite` je v `app/src/main/assets/`. Pri spustení ju `BundledDatabase.install(versionCode)` skopíruje do `context.getDatabasePath("venues.sqlite")`, ak tam chýba alebo ak sa líši uložená verzia (malý textový súbor vedľa DB s `versionCode` aplikácie, z ktorej bola skopírovaná). Kopíruje sa do dočasného súboru v tom istom priečinku a potom sa premenuje (žiadna polovičná DB po páde). Otvára sa iba na čítanie (`SQLiteDatabase.OPEN_READONLY`). Kopírovanie aj čítanie beží mimo hlavného vlákna (`Dispatchers.IO`). `BundledDatabase.install` nie je bezpečné volať súbežne (pevný názov dočasného súboru) — aplikácia ho volá **najviac raz naraz** (jediné volanie pri načítaní dát v `MapViewModel`, prípadne serializované cez `Mutex`). Chýbajúci asset alebo chyba DB → `MapUiState.loadError = true`, UI zobrazí „Dáta sa nepodarilo načítať" a aplikácia nespadne.
13. **Hlavná kategória a farba pinu** — hlavná kategória zariadenia je jeho prvá kategória v poradí deklarácie `VenueCategory` (§6); farba pinu je jej `colorHex`. Zariadenie bez známej kategórie má sivú farbu `#757575`.
14. **Poloha** — povolenie sa žiada cez Activity Result API naraz pre `ACCESS_FINE_LOCATION` a `ACCESS_COARSE_LOCATION`; ak používateľ udelí iba približnú polohu, aplikácia funguje rovnako (len s menšou presnosťou). `LocationService.locations()` je `Flow<GeoPoint?>` nad `LocationManager` (providery `GPS_PROVIDER` a `NETWORK_PROVIDER`, ak sú zapnuté; `minTime` 5 s, `minDistance` 20 m; najprv emituje poslednú známu polohu). Pri zrušení `Flow` sa odhlási z aktualizácií. Bez povolenia emituje `null`. Povolenie aj zapnuté providery sa zisťujú iba pri začatí zberu, preto UI (krok 8) zbiera `locations()` cez `repeatOnLifecycle(Lifecycle.State.STARTED)` a výsledok posiela do `MapViewModel.updateUserLocation` — zber sa tak reštartuje pri každom návrate do aplikácie (napr. po zapnutí polohy v rýchlych nastaveniach) a po udelení povolenia sa spustí nanovo (zmena stavu povolenia je kľúč pre reštart zberu).

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
│   └── make_test_fixture.py      # vytvorí frontend/app/src/test/resources/test_venues.sqlite (od kroku 4a)
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

Obsah testovacej DB (`make_test_fixture.py`) sa pri prechode na Nominatim ani na Android **nemení** (hodnoty `gps_source` vo fixture sú iba informatívne, aplikácia ich nečíta). V kroku 4a sa mení iba **cesta** výstupu z `frontend/SportNavTests/Fixtures/` (iOS) na `frontend/app/src/test/resources/` (Android). V kroku 4b pribudne jediné nové zariadenie č. 10 (NULL `street` a `city`, §8.11); zariadenia 1–9 ostávajú bez zmeny.

### 9.2 Frontend — Android aplikácia (Kotlin, minSdk 26)

Balík (`applicationId` aj `namespace`): `sk.sportnav`.

```
frontend/                                      # Android Gradle projekt (krok 4, šablóna Android Studio)
├── settings.gradle.kts, build.gradle.kts, gradle.properties
├── gradle/libs.versions.toml                  # verzie závislostí §4.2
├── gradlew, gradlew.bat, gradle/wrapper/
└── app/
    ├── build.gradle.kts                       # minSdk 26, Compose, závislosti §4.2
    └── src/
        ├── main/
        │   ├── AndroidManifest.xml            # §4.3
        │   ├── assets/venues.sqlite           # výstup backend/scripts/build_db.py (krok 9)
        │   ├── java/sk/sportnav/
        │   │   ├── MainActivity.kt            # MapLibre.getInstance, povolenie polohy, MapScreen
        │   │   ├── model/
        │   │   │   ├── Venue.kt               # Venue, DaySchedule, Weekday, GeoPoint, todaySchedule (§6, §8.10)
        │   │   │   └── VenueCategory.kt
        │   │   ├── data/
        │   │   │   ├── VenueRepository.kt     # interface VenueRepository + SQLiteVenueRepository
        │   │   │   └── BundledDatabase.kt     # kopírovanie DB z assets (§8.12)
        │   │   ├── location/
        │   │   │   ├── LocationService.kt     # LocationManager → Flow<GeoPoint?> (§8.14)
        │   │   │   └── Distance.kt            # distanceMeters, Haversine (§8.7)
        │   │   ├── navigation/
        │   │   │   └── NavigationService.kt   # MapApp, AppAvailability, NavigationTarget (§5.4)
        │   │   ├── viewmodel/
        │   │   │   ├── FilterState.kt
        │   │   │   └── MapViewModel.kt        # MapUiState, filtrovanie, výber zariadenia
        │   │   └── ui/
        │   │       ├── MapScreen.kt
        │   │       ├── VenueMapView.kt        # AndroidView nad MapLibre MapView (§8.6)
        │   │       ├── FilterSheet.kt
        │   │       ├── VenueCardSheet.kt      # vrátane OSM atribúcie (§5.3)
        │   │       ├── NavigationChooser.kt   # dialóg výberu aplikácie (§5.4)
        │   │       └── CategoryUi.kt          # VenueCategory.labelRes(), VenueCategory.icon()
        │   └── res/
        │       ├── values/strings.xml         # en (predvolený jazyk)
        │       ├── values-sk/strings.xml
        │       └── values-cs/strings.xml
        └── test/
            ├── resources/test_venues.sqlite   # testovacia DB z make_test_fixture.py (krok 4a)
            └── java/sk/sportnav/
                ├── model/DayScheduleTest.kt
                ├── data/SQLiteVenueRepositoryTest.kt   # Robolectric
                ├── data/BundledDatabaseTest.kt
                ├── location/DistanceTest.kt
                ├── navigation/NavigationServiceTest.kt
                └── viewmodel/MapViewModelTest.kt
```

**Rozhrania (Kotlin):**

```kotlin
interface VenueRepository {
    fun loadVenues(): List<Venue>                      // iba gps_pending = 0; pri chybe DB vyhodí výnimku
}
class SQLiteVenueRepository(private val databaseFile: () -> File) : VenueRepository

class BundledDatabase(
    private val target: File,                          // context.getDatabasePath("venues.sqlite")
    private val versionFile: File,                     // vedľa DB; versionCode poslednej kópie
    private val source: () -> InputStream,             // context.assets.open("venues.sqlite")
) {
    fun install(versionCode: Long): File               // §8.12
}

fun todaySchedule(hours: List<DaySchedule>, today: Weekday): List<DaySchedule>   // §8.10
fun distanceMeters(a: GeoPoint, b: GeoPoint): Double                             // §8.7

data class FilterState(
    val categories: Set<VenueCategory> = emptySet(),   // prázdne = všetky
    val maxDistanceKm: Double = 5.0,                   // 0.5 ... 20
)

enum class MapApp { GOOGLE_MAPS, WAZE, OTHER_GEO }
interface AppAvailability {                            // implementácia nad PackageManager; v testoch fake
    fun isInstalled(packageName: String): Boolean
    fun geoHandlerPackages(): Set<String>              // balíky, ktoré vedia otvoriť geo: URI
}
data class NavigationTarget(val uri: String, val packageName: String?)
class NavigationService {
    fun availableApps(availability: AppAvailability): List<MapApp>   // poradie GOOGLE_MAPS, WAZE, OTHER_GEO
    fun target(app: MapApp, point: GeoPoint, label: String): NavigationTarget   // §5.4
}

class LocationService(context: Context) {
    fun locations(): Flow<GeoPoint?>                   // §8.14
}

data class MapUiState(
    val visibleVenues: List<Venue> = emptyList(),
    val filter: FilterState = FilterState(),
    val selectedVenue: Venue? = null,
    val userLocation: GeoPoint? = null,
    val loadError: Boolean = false,
)
class MapViewModel(
    repository: VenueRepository,
    ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    val uiState: StateFlow<MapUiState>
    fun updateFilter(filter: FilterState)
    fun updateUserLocation(location: GeoPoint?)
    fun selectVenue(id: Int?)
    fun distanceTo(venue: Venue): Double?              // metre; null bez polohy
}
```

Doménová logika (`model/`, `location/Distance.kt`, `navigation/`, `viewmodel/`) nepoužíva Android triedy, aby sa dala testovať na čistom JVM; Android API je iba v `data/`, `location/LocationService.kt`, implementácii `AppAvailability` a v `ui/`.

---

## 10. Poradie implementácie

Každý krok sa dá samostatne implementovať a overiť príkazom `/implement DESIGN.md <číslo kroku>`.

| # | Krok | Kto | Výstup | Overenie |
|---|---|---|---|---|
| 1 | **Backend základ** — `requirements.txt`, `.env.example`, koreňový `.gitignore`, `sportnav_data/__init__.py`, `categories.py`, `opening_hours.py` + testy | agent | moduly §9.1 | `pytest` (categories, opening_hours) |
| 2 | **Enrich** — `enrich.py`: Nominatim (POI → adresa → `gps_pending`), sekvenčný `enrich_all` s `min_interval` + testy s `httpx.MockTransport` | agent | `enrich.py` | `pytest` (bez reálnej siete) |
| 3 | **Export + CLI** — `export.py` (schéma presne podľa §3.3), `scripts/build_db.py`, testovacia fixture DB (pôvodne `frontend/SportNavTests/Fixtures/test_venues.sqlite`, od kroku 4a `frontend/app/src/test/resources/test_venues.sqlite`) + testy | agent | `export.py`, `build_db.py`, fixture DB | `pytest` |
| 3a | **Prechod na Nominatim** (refaktor už implementovaných krokov 1–3; pôvodne Apple Maps + Google Places) — prepísať `sportnav_data/enrich.py` (§3.2, §8.3, §8.4, §8.9, §9.1), `sportnav_data/opening_hours.py` (OSM syntax, §8.5), `scripts/build_db.py` (§9.1), `.env.example`, `backend/README.md`; nahradiť testy `tests/test_enrich.py`, `tests/test_opening_hours.py` a časť `# --- build_db CLI` v `tests/test_export.py` (§11.1); odstrániť fixtures `apple_*.json` / `google_*.json` a pridať `nominatim_*.json`. Vo zvyšku `tests/test_export.py` (testy exportu) sa smú zmeniť iba vzorové hodnoty `gps_source` (`apple_maps` → `nominatim_poi`). **Nemeniť:** `categories.py`, `export.py`, schému §3.3, `make_test_fixture.py`, fixture DB ani nič vo `frontend/`. Mimo `make_test_fixture.py` (jeho hodnoty `gps_source` sú historické a informatívne, §9.1) nesmie v `backend/` ostať žiadna zmienka o Apple Maps Server API, Google Places, `APPLE_MAPS_AUTH_TOKEN` ani `GOOGLE_API_KEY`. | agent | §9.1 | `pytest` |
| 4 | **Android Studio projekt** — nainštalovať Android Studio (zadarmo, bez účtu) a Android SDK; New Project → *Empty Activity* (Compose), názov `SportNav`, balík `sk.sportnav`, umiestnenie `frontend/` (ak Android Studio odmietne neprázdny priečinok, vytvoriť projekt inde a jeho obsah presunúť do `frontend/`; `frontend/README.md` ponechať), Minimum SDK **API 26**, build jazyk **Kotlin DSL**. Nastaviť `JAVA_HOME` na JDK z Android Studio (`<Android Studio>\jbr`), aby `./gradlew` fungoval v termináli. Vytvoriť emulátor (AVD) so systémovým obrazom **Google Play** (obsahuje Google Maps na test navigácie). Commitnúť vrátane `.gitignore` zo šablóny. | **človek (Windows)** | `frontend/` Gradle projekt | `cd frontend && ./gradlew assembleDebug` prejde |
| 4a | **Backend → Android cesty** — v `backend/scripts/make_test_fixture.py` zmeniť `DEFAULT_OUTPUT` na `frontend/app/src/test/resources/test_venues.sqlite`, DB vygenerovať (`python scripts/make_test_fixture.py`), odstrániť `frontend/SportNavTests/`. Výstupnú cestu reálnej DB v `backend/README.md` a v docstringu `scripts/build_db.py` zmeniť na `../frontend/app/src/main/assets/venues.sqlite` (krok 9). Zmienky o iOS v docstringoch, popisoch CLI a komentároch backendu (`make_test_fixture.py`, `tests/test_export.py`, `backend/README.md`) prepísať na Android. **Obsah testovacej DB, logika backendu, schéma §3.3 ani nič vo `frontend/` mimo odstránenia `SportNavTests/` a novej testovacej DB sa nemenia (§9.1).** Tento krok sa dá robiť pred krokom 4 aj po ňom. | agent | testovacia DB na novej ceste, backend bez iOS ciest | `pytest` |
| 4b | **Zariadenie s NULL ulicou a mestom v testovacej DB** (pre test §8.11 v kroku 5) — do `FIXTURE_VENUES` v `backend/scripts/make_test_fixture.py` pridať zariadenie `id = 10`: vstup `street = ""` a `city = None` (exportér oboje uloží ako NULL), s GPS (`gps_pending = 0`), jednou známou kategóriou (`wellness-a-relax-10`), bez otváracích hodín, telefónu a webu; komentár v štýle ostatných (`# 10: NULL street and city -> mapped to "" by the app (section 8.11)`). DB vygenerovať nanovo. V `test_fixture_db_contents` (`tests/test_export.py`) doplniť kontrolu, že existuje zariadenie s GPS, ktoré má `street IS NULL AND city IS NULL`. Zariadenia 1–9, ostatné testy, logika backendu a schéma §3.3 sa nemenia. | agent | testovacia DB s 10 zariadeniami | `pytest` |
| 5 | **Modely + dáta** — `model/Venue.kt`, `model/VenueCategory.kt` (§6, §8.13), `todaySchedule`, `data/VenueRepository.kt` (`SQLiteVenueRepository`, §8.1, §8.11), `data/BundledDatabase.kt` (§8.12); Robolectric a JUnit do `libs.versions.toml` / `app/build.gradle.kts` + testy (§11.2) | agent | §9.2 model, data | `./gradlew testDebugUnitTest` |
| 6 | **Služby** — `location/Distance.kt` (§8.7), `location/LocationService.kt` (§8.14), `navigation/NavigationService.kt` + implementácia `AppAvailability` nad `PackageManager` (§5.4) + testy | agent | §9.2 location, navigation | `./gradlew testDebugUnitTest` |
| 7 | **ViewModel** — `FilterState`, `MapUiState`, `MapViewModel` (filter podľa kategórie a vzdialenosti, §8.7; `loadError`, §8.12) + testy s `kotlinx-coroutines-test` | agent | §9.2 viewmodel | `./gradlew testDebugUnitTest` |
| 8 | **UI** — závislosť MapLibre; `MainActivity` (povolenie polohy, §8.14), `MapScreen`, `VenueMapView` (§8.6), `FilterSheet`, `VenueCardSheet` (vrátane OSM atribúcie, §5.3), `NavigationChooser` (§5.4), `CategoryUi`, `AndroidManifest.xml` (§4.3), `strings.xml` (en/sk/cs). Pred manuálnym testom musí byť v `assets/` DB — z kroku 9, alebo dočasne kópia testovacej DB (necommitovať). | agent | §9.2 ui, manifest, res | `./gradlew assembleDebug testDebugUnitTest` + manuálny checklist §11.3 v emulátore |
| 9 | **Reálne dáta** — spustiť Apify Actor v bezplatnom účte Apify (webová konzola, bez tokenu; vstup `categories` = 7 slugov z §3.1), uložiť `backend/data/venues_raw.json`, spustiť `cd backend && python scripts/build_db.py --input data/venues_raw.json --output ../frontend/app/src/main/assets/venues.sqlite` (beží ~2 s na zariadenie kvôli limitu 1 požiadavka/s) | **človek** | `venues.sqlite` v assets | počet záznamov, podiel `gps_pending` (§12) |

Všetky kroky sa dajú robiť na Windows. Kroky 5–8 vyžadujú Android Studio a SDK z kroku 4. Krok 9 nezávisí od krokov 4–8 a môže prebehnúť kedykoľvek po kroku 3a.

Príkazy `./gradlew …` platia pre Git Bash; v PowerShelli `.\gradlew.bat …`.

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

### 11.2 Android (JUnit 4 + Robolectric, lokálne unit testy)

Príkaz: `cd frontend && ./gradlew testDebugUnitTest` (build: `./gradlew assembleDebug`). Testy nesmú volať sieť ani vyžadovať emulátor.

| Oblasť | Testované prípady |
|---|---|
| `SQLiteVenueRepository` (Robolectric, testovacia DB z `test/resources` skopírovaná do dočasného súboru) | načíta všetky zariadenia s GPS z fixture DB; zariadenia s `gps_pending = 1` vynechá; kategórie a otváracie hodiny sú namapované (vrátane `closes < opens`, §8.10); NULL `street`/`city` sa namapuje na `""` (§8.11, zariadenie 10 z fixture DB); zariadenia 8 a 9 z fixture DB (neznáma kategória, §8.2) sa načítajú s prázdnymi, resp. zníženými kategóriami; poškodený / chýbajúci súbor → výnimka |
| `BundledDatabase` (JVM, dočasný priečinok) | prvé `install` skopíruje DB a zapíše verziu; druhé `install` s rovnakou verziou nekopíruje (zdroj sa neotvorí); iná verzia → nová kópia; chyba pri kopírovaní nenechá polovičnú DB na cieľovej ceste |
| `todaySchedule` | vráti iba riadky daného dňa vrátane viacerých blokov; `closes < opens` ostane bez úpravy; prázdne hodiny → prázdny zoznam |
| `distanceMeters` | rovnaký bod → 0; Praha (50.0755, 14.4378) – Brno (49.1951, 16.6068) ≈ 185 km (tolerancia ±1 km); symetria |
| `NavigationService` | presný tvar URI a balíka pre všetky 3 aplikácie; desatinná bodka aj pri `Locale.setDefault(Locale("sk"))`; URL-enkódovanie názvu s diakritikou a zátvorkami; `availableApps` s fake `AppAvailability`: nič / iba Google Maps / Google Maps + Waze / `geo:` vie iba Google Maps (→ bez `OTHER_GEO`) / `geo:` vie aj iná aplikácia (→ `OTHER_GEO`) |
| `MapViewModel` (fake repository, `StandardTestDispatcher`) | prázdny filter → všetky; filter kategórie (zariadenie s viacerými kategóriami vyhovie, ak sa zhoduje aspoň jedna); filter vzdialenosti (hraničné hodnoty 0,5 a 20 km); bez polohy → filter vzdialenosti sa neaplikuje a `distanceTo` je `null`; `selectVenue` / zrušenie výberu; repository vyhodí výnimku → `loadError = true` bez pádu |

### 11.3 Manuálny checklist (emulátor s obrazom Google Play alebo vlastný telefón)

- prvé spustenie → systémový dialóg polohy; po zamietnutí sa mapa zobrazí bez pádu a vycentruje na oblasť zariadení
- s udelenou iba „približnou polohou" aplikácia funguje
- mapa OpenFreeMap sa načíta; atribúcia mapy je viditeľná
- piny sú farebne odlíšené a pri oddialení sa zhlukujú; ťuknutie na zhluk mapu priblíži
- modrá bodka so šípkou smeru (v emulátore nastaviť polohu cez *Extended controls → Location*)
- ťuknutie na pin → karta s názvom, kategóriou, vzdialenosťou, hodinami a atribúciou „© OpenStreetMap contributors"
- „Navigovať" → priame otvorenie (1 aplikácia) alebo dialóg (viac aplikácií); Google Maps v emulátore spustí navigáciu
- filter mení piny na mape; jazyk aplikácie sk/cs/en (podľa jazyka systému)
- režim lietadla → mapa bez dlaždíc, ale piny, karta a filter fungujú a aplikácia nespadne
- otočenie displeja → mapa ani výber sa nestratia a aplikácia nespadne

---

## 12. Riziká

| Riziko | Dopad | Mitigácia |
|---|---|---|
| Verejná inštancia OpenFreeMap nemá garantovanú dostupnosť (bez SLA) | mapa bez podkladu | piny, karta, filter a navigácia fungujú aj bez dlaždíc (§8.6); URL štýlu je jediná konštanta — prechod na iný zdroj dlaždíc je samostatná iterácia návrhu |
| Kombinácia MapLibre Native Android + OpenFreeMap nie je v tomto projekte ešte overená (OpenFreeMap uvádza podporu MapLibre Native, nie konkrétne Android) | mapa sa nezobrazí alebo chýba písmo pre počty v zhlukoch | v kroku 8 najprv overiť zobrazenie štýlu Liberty v emulátore; pri probléme s písmom zobraziť zhluky bez čísla |
| Robolectric so SQLite nemusí na Windows bežať | testy repository v kroku 5 nepôjdu | náhradou sú inštrumentované testy (`./gradlew connectedDebugAndroidTest`) v emulátore; odchýlku zapísať do Implementation Report |
| Desatinná čiarka v slovenskom / českom locale | rozbité navigačné URI | formátovanie s `Locale.ROOT` (§5.4) + test so slovenským locale (§11.2) |
| Package visibility (Android 11+) | aplikácia nevidí Google Maps / Waze, ponúkne iba „Iná mapová aplikácia" alebo nič | `<queries>` v manifeste (§4.3) + manuálny test v emulátore s Google Play |
| Životný cyklus `MapView` v Compose | únik pamäte alebo pád pri otočení displeja | preposielanie lifecycle udalostí (§8.6) + bod v checkliste §11.3 |
| Inštalácia Android Studio, SDK a emulátora (niekoľko GB), nastavenie `JAVA_HOME` | agenti nevedia zbuildiť projekt | krok 4 robí človek a overí `./gradlew assembleDebug` pred spustením krokov 5–8 |
| Emulátor bez Google Play neobsahuje Google Maps | navigáciu nejde otestovať | AVD so systémovým obrazom Google Play (krok 4) |
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
