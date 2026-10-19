# SportNav – Technická dokumentácia iOS aplikácie

*4. októbra 2026*

---

## 1. Executive Summary

SportNav je natívna iOS aplikácia určená pre držiteľov Multisport karty, ktorá im umožňuje v reálnom čase nájsť najbližšie akceptované športovisko, filtrovať zariadenia podľa typu aktivity a spustiť navigáciu priamo z aplikácie. Aplikácia rieši problém roztrieštenosti informácií o partnerských zariadeniach Multisport a absencie intuitívnej navigácie k nim.

**Cieľová platforma:** iOS 16+\
**Cieľová skupina:** Držitelia Multisport karty (SK, CZ, HU, PL)\
**Distribucia:** App Store\
**Jazyk rozhrania:** SK, CZ, EN

---

## 2. Architektúra aplikácie

SportNav využíva **MVVM + Clean Architecture** rozdelené do štyroch vrstiev:

### Prezentačná vrstva (UI)

- SwiftUI views a ViewModels
- Kombinácia SwiftUI (hlavné obrazovky) a UIKit (MapKit integrácia)
- Reactive binding cez Combine framework

### Doménová vrstva (Business Logic)

- Use Cases: SearchVenuesUseCase, NavigateToVenueUseCase, FilterVenuesUseCase
- Domain modely: Venue, VenueCategory, Route, UserLocation
- Interfaces / Protokoly pre repozitáre

### Dátová vrstva (Data)

- **Remote:** REST API klient (URLSession + async/await)
- **Lokálna cache:** Core Data (offline prístup k nacachovaným športoviskám)
- **Lokácia:** CoreLocation service
- **Mapy:** MapKit / Apple Maps

### Infraštruktúra

- Push notifikácie (APNs)
- Analytics: Firebase Analytics
- Crash reporting: Firebase Crashlytics
- CI/CD: Xcode Cloud

---

## 3. Získavanie dát z Multisport

### ⚠️ Pravidlo nulových nákladov na externe API

> **Žiadne platené API volania v produkcii.** Všetky externé volania musia byť buď zadarmo, alebo jednorazové (pri vývoji / importe dát). GPS súradnice a otváracie hodiny sa ukladajú do vlastnej DB a ďalej sa nevolajú.

---

### Krok 1 – Scraping zoznamu zariadení (Apify Actor)

Namiesto vlastného scrapera používame hotový **Apify Actor** od Jana Buchara: [`janbuchar/multisport-map-scraper`](https://apify.com/janbuchar/multisport-map-scraper).

**Čo Actor robí:** Prechádza všetky kategórie aktivít na `mapa.multisport.cz`, zbiera každé venue ID a scrapuje detail page každého zariadenia do štruktúrovaného záznamu.

**Výstup jedného záznamu:**

```json
{
  "id": 193,
  "url": "https://mapa.multisport.cz/cs/193",
  "title": "Legion Gym",
  "description": "Fitness a Skupinové lekce (TRX, Funkční trénink, Strečink)",
  "categories": ["Posilovny a silové tréninky", "Skupinové a taneční lekce"],
  "activities": ["Funkční trénink", "Posilovna", "Stretching"],
  "street": "Husova 100",
  "city": "Jaroměř",
  "phone": "+420 606 182 647",
  "email": "info@legiongym.cz",
  "website": "http://legiongym.cz/",
  "facebook": "https://www.facebook.com/legiongymjaromer"
}
```

**Vstupné kategórie (slugy):**

| Slug | Kategória |
| --- | --- |
| `bazeny-a-vodni-sporty-1` | Bazény a vodní sporty |
| `rodice-s-detmi-2` | Rodiče s dětmi |
| `joga-a-zdravotni-cviceni-3` | Jóga a zdravotní cvičení |
| `lezecke-steny-4` | Lezecké stěny |
| `posilovny-a-silove-treninky-5` | Posilovny a silové tréninky |
| `pro-tehotne-6` | Pro těhotné |
| `raketove-a-micove-sporty-7` | Raketové a míčové sporty |
| `sezonni-a-ostatni-aktivity-8` | Sezónní a ostatní aktivity |
| `skupinove-a-tanecni-lekce-9` | Skupinové a taneční lekce |
| `wellness-a-relax-10` | Wellness a relax |

**Python integrácia:**

```python
from apify_client import ApifyClient

client = ApifyClient("APIFY_API_TOKEN")

# Všetky kategórie – prázdne pole = scrape all
run = client.actor("janbuchar/multisport-map-scraper").call(
    run_input={"categories": []}
)

venues_raw = list(
    client.dataset(run["defaultDatasetId"]).iterate_items()
)
```

**Cena Apify:** Pay-per-usage; free tier pokryje periodické spúšťanie pri \~5 000 zariadeniach. Periodicita: **1× týždenne** (nie každých 6h — GPS sa nemení, hodiny len zriedka).

**Obmedzenia Actor-a (čo chýba a treba doplniť):**

| Chýbajúce pole | Riešenie |
| --- | --- |
| GPS súradnice (lat/lon) | Krok 2 – Apple Maps Server API |
| Otváracie hodiny | Krok 2 – Apple Maps Server API |
| Pokrytie SK (actor scrape CZ mapu) | Overiť trial runom; ak chýba SK, forknúť a upraviť |

---

### Krok 2 – Obohacovanie dát: GPS + otváracie hodiny

**Pravidlo:** GPS súradnice a hodiny sa získajú **jednorazovo pri prvom importe** a uložia do vlastnej DB. Ďalej sa nevolá žiadne externé API — nulové prevádzkové náklady.

#### Primárny zdroj: Apple Maps Server API (zadarmo)

Apple Maps Server API je zadarmo v rámci Apple Developer Program ($99/rok, ktorý tak či tak potrebujeme pre App Store). Prijíma textový dopyt + mesto a vracia GPS, otváracie hodiny, kontakt a kategóriu.

```python
import httpx
import jwt, time, uuid

def get_apple_maps_token(key_id, team_id, private_key_pem):
    """Generuje krátkodobý JWT token pre Apple Maps Server API."""
    now = int(time.time())
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + 1800,  # 30 minút
    }
    headers = {"kid": key_id, "id": f"{team_id}.{key_id}"}
    return jwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)

async def enrich_venue_apple(venue: dict, token: str) -> dict:
    """Doplní GPS + hodiny cez Apple Maps Server API (zadarmo)."""
    query = f"{venue['title']} {venue['street']} {venue['city']}"
    url = "https://maps-api.apple.com/v1/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": query,
        "lang": "sk-SK",
        "resultTypeFilter": "Poi",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params=params)
        data = resp.json()

    if not data.get("results"):
        return venue  # fallback na Google (krok nižšie)

    place = data["results"][0]
    venue["lat"] = place["center"]["lat"]
    venue["lon"] = place["center"]["lng"]
    venue["opening_hours"] = place.get("openingHours", {})
    venue["apple_place_id"] = place.get("id")
    venue["gps_source"] = "apple_maps"
    return venue
```

**Čo Apple Maps Server API vracia:**

- `center.lat` / `center.lng` — GPS súradnice
- `openingHours` — štruktúrované otváracie hodiny
- `phoneNumber`, `url` — kontakt
- `category` — typ miesta

---

#### Fallback (jednorazový, len pri vývoji): Google Places API

Ak Apple Maps nevráti výsledok (žiadny hit alebo nízka istota), použijeme Google Places API **iba jednorazovo počas development importu**. V produkcii sa Google Places nevolá nikdy.

Google poskytuje $200 mesačný kredit (\~11 700 Text Search Pro volaní zadarmo). Jednorazový import \~5 000 zariadení = $0 (ostaneme v kredite).

```python
import httpx

GOOGLE_API_KEY = "AIza..."  # len dev prostredie, nikdy v produkcii

async def enrich_venue_google_fallback(venue: dict) -> dict:
    """Jednorazový fallback pri importe – nikdy v produkcii."""
    query = f"{venue['title']} {venue['street']} {venue['city']}"
    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": query,
        "inputtype": "textquery",
        "fields": "geometry,opening_hours,place_id",
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

### Krok 3 – Pipeline (celkový tok)

```
[Apify Actor]
janbuchar/multisport-map-scraper
  → zoznam všetkých zariadení (názov, adresa, kategória, kontakt)
  → chýba: GPS, hodiny
        ↓
[Enrich pipeline – Python backend, 1× týždenne]
  Pre každé zariadenie bez GPS:
    1. Apple Maps Server API  ← primárny (zadarmo)
       ├─ hit  → uloží GPS + hodiny do DB ✅
       └─ miss → Google Places API fallback (jednorazovo, dev kredity)
                  → uloží GPS + hodiny do DB ✅
        ↓
[PostgreSQL + PostGIS DB]
  Kompletný záznam:
  id, name, categories, address, lat, lon,
  opening_hours, phone, website, gps_source
        ↓
[SportNav REST API]  ←  iOS aplikácia
```

---

### Pravidlo čistoty dát (GPS rule)

1. GPS sa ukladá **raz** a aktualizuje len ak sa zmení adresa zariadenia
2. Otváracie hodiny sa refreshujú **1× týždenne** (len cez Apple Maps, zadarmo)
3. Google Places sa **nikdy nevolá** v produkčnom prostredí — len dev import
4. Ak pre zariadenie neexistuje GPS ani po oboch pokusoch, zariadenie sa označí `gps_pending` a zobrazí sa bez mapy (len v zozname)

---

### Dátová štruktúra záznamu po obohacovaní

```json
{
  "id": "venue_193",
  "multisport_id": 193,
  "name": "Legion Gym",
  "categories": ["fitness", "group_classes"],
  "activities": ["Funkční trénink", "Posilovna", "Stretching"],
  "address": {
    "street": "Husova 100",
    "city": "Jaroměř",
    "zip": "55101",
    "country": "CZ"
  },
  "coordinates": { "lat": 50.3564, "lon": 15.9195 },
  "gps_source": "apple_maps",
  "opening_hours": {
    "mon": "06:00-22:00",
    "tue": "06:00-22:00",
    "wed": "06:00-22:00",
    "thu": "06:00-22:00",
    "fri": "06:00-21:00",
    "sat": "08:00-18:00",
    "sun": "09:00-16:00"
  },
  "phone": "+420 606 182 647",
  "email": "info@legiongym.cz",
  "website": "http://legiongym.cz/",
  "multisport_accepted": true,
  "gps_pending": false,
  "last_updated": "2026-10-04T06:00:00Z"
}
```

---

## 4. Dátový model

### Hlavné entity

**Venue (Športovisko)**

- id, multisport_id, name, slug
- categoryIds: \[VenueCategory\]
- coordinates: CLLocationCoordinate2D
- gpsSource: GPSSource (apple_maps | google_fallback | manual | pending)
- address: Address
- openingHours: \[DaySchedule\]
- multisportAccepted: Bool
- acceptedCardTypes: \[CardType\]
- rating: Double?
- imageURLs: \[URL\]
- lastUpdated: Date

**VenueCategory**

- id (enum): fitness, pool, tennis, squash, yoga, football, cycling, climbing, golf, spa, group_classes, wellness
- displayName: String (lokalizovaný)
- iconName: String (SF Symbols)
- multisportSlug: String (mapovanie na Apify kategóriu)

**UserFavorite**

- userId: String
- venueId: String
- addedAt: Date

**SearchFilter**

- categoryIds: \[String\]
- maxDistanceKm: Double
- openNow: Bool
- cardType: CardType

**Route**

- origin: CLLocationCoordinate2D
- destination: CLLocationCoordinate2D
- travelMode: TravelMode (walking, driving, cycling)
- estimatedDurationMin: Int
- distanceKm: Double
- steps: \[RouteStep\]

---

## 5. Kľúčové obrazovky a navigačný tok (UI/UX)

### Obrazovky

| Obrazovka | Popis |
| --- | --- |
| Onboarding (3 slides) | Predstavenie funkcií, výzva na povolenie lokácie |
| Mapa (Home) | Interaktívna mapa s pinmi športovísk, geolocate button, filter FAB |
| Zoznam zariadení | ListView s vzdialenosťou, kategóriou a ikonou, zoradenie podľa blízkosti |
| Filter sheet | Výber kategórie, max. vzdialenosť (slider), prepínač „otvorené teraz" |
| Detail zariadenia | Foto, meno, kategória, hodiny, „Navigovať" button, zdieľanie |
| Navigácia | Fullscreen MapKit navigácia, ETA, turn-by-turn inštrukcie |
| Obľúbené | Uložené zariadenia, offline dostupné |
| Nastavenia | Jazyk, typ karty, notifikácie, O aplikácii |

### Navigačný tok

```
App Launch
  └─ Onboarding (1× pri prvom spustení)
       └─ Povolenie lokácie
            └─ Mapa (Home)
                 ├─ Vyhľadávanie → Zoznam → Detail → Navigácia
                 ├─ Filter sheet → Mapa (filtrovaná)
                 └─ Profil → Obľúbené / Nastavenia
```

---

## 6. Navigačný modul

### Technológie

- **CoreLocation** – real-time GPS poloha, geofencing pri príchode k cieľu
- **MapKit** – renderovanie máp (Apple Maps), anotácie, overlays
- **MKDirections API** – výpočet trasy a turn-by-turn krokov (zadarmo, súčasť iOS SDK)
- **CLLocationManager** – always-on lokácia (iba počas aktívnej navigácie)

### Implementácia

```swift
// LocationService.swift
class LocationService: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var currentLocation: CLLocation?

    func requestAuthorization() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }
}

// NavigationViewModel.swift
class NavigationViewModel: ObservableObject {
    @Published var route: MKRoute?
    @Published var currentStep: MKRoute.Step?

    func calculateRoute(to venue: Venue) async {
        let request = MKDirections.Request()
        request.source = MKMapItem.forCurrentLocation()
        request.destination = MKMapItem(placemark:
            MKPlacemark(coordinate: venue.coordinates))
        request.transportType = .automobile
        let directions = MKDirections(request: request)
        let response = try? await directions.calculate()
        self.route = response?.routes.first
    }
}
```

### Fallback

Ak MapKit nefunguje (offline), zobrazíme cached mapu dlaždíc a statickú adresu zariadenia.

---

## 7. Backend a API špecifikácia

### Infraštruktúra

- **Cloud:** AWS (alebo GCP) – EC2/ECS pre API, RDS PostgreSQL pre DB
- **API Framework:** FastAPI (Python) alebo Node.js + Express
- **CDN:** CloudFront pre obrázky zariadení
- **Cache:** Redis – výsledky vyhľadávania a geospatial queries

### Hlavné endpointy

| Metóda | Endpoint | Popis |
| --- | --- | --- |
| GET | /v1/venues | Zoznam všetkých zariadení (stránkovaný) |
| GET | /v1/venues/nearby | Zariadenia v okruhu (lat, lon, radius) |
| GET | /v1/venues/{id} | Detail zariadenia |
| GET | /v1/venues/categories | Zoznam kategórií |
| GET | /v1/venues/search | Fulltextové vyhľadávanie |
| POST | /v1/users/favorites | Pridanie obľúbeného |
| DELETE | /v1/users/favorites/{id} | Odobranie obľúbeného |

### Príklad odpovede /v1/venues/nearby

```
GET /v1/venues/nearby?lat=48.1486&lon=17.1077&radius=3000&category=fitness
Authorization: Bearer <token>
```

```json
{
  "data": [...],
  "meta": {
    "total": 12,
    "radius_m": 3000,
    "center": {"lat": 48.1486, "lon": 17.1077}
  }
}
```

### Autentifikácia

- JWT tokeny (access 1h + refresh 30d)
- Sign in with Apple (povinné pre App Store)

---

## 8. Bezpečnosť, oprávnenia a GDPR

### iOS oprávnenia (Info.plist)

| Kľúč | Dôvod |
| --- | --- |
| NSLocationWhenInUseUsageDescription | Nájdenie najbližšieho športoviska |
| NSLocationAlwaysUsageDescription | Aktívna navigácia na pozadí |
| NSCameraUsageDescription | Skenovanie Multisport karty |
| NSPhotoLibraryUsageDescription | Pridanie fotky zariadenia |
| NSMicrophoneUsageDescription | Hlasové vyhľadávanie |

### GDPR opatrenia

- Dáta o polohe sa neuchovávajú na serveri (len real-time)
- História navigácií uložená iba lokálne (Keychain / Core Data, šifrované)
- Explicitný súhlas pri prvom spustení
- Možnosť vymazania účtu a všetkých dát (GDPR Art. 17)
- Privacy Manifest (požadovaný Apple od iOS 17)
- Žiadne predávanie dát tretím stranám

### Bezpečnosť API

- HTTPS everywhere (TLS 1.3)
- Certificate pinning v iOS klientovi
- Rate limiting na API (100 req/min na IP)
- API kľúče uložené v AWS Secrets Manager
- **Google Places API kľúč existuje iba v dev prostredí** – nikdy sa nedostane do produkčného buildu ani do iOS aplikácie

---

## 9. Technologický stack

| Vrstva | Technológia | Náklady |
| --- | --- | --- |
| Jazyk | Swift 5.9+ | zadarmo |
| UI Framework | SwiftUI + UIKit (hybridne) | zadarmo |
| Reaktivita | Combine + async/await | zadarmo |
| Mapy & navigácia | MapKit + CoreLocation + MKDirections | zadarmo (iOS SDK) |
| Sieť | URLSession + async/await | zadarmo |
| Lokálna DB | Core Data | zadarmo |
| Autentifikácia | Sign in with Apple, JWT | zadarmo |
| Analytics | Firebase Analytics | zadarmo (free tier) |
| Crash reporting | Firebase Crashlytics | zadarmo |
| Push notifikácie | APNs + Firebase Messaging | zadarmo |
| Backend | FastAPI (Python) / Node.js | podľa servera |
| Databáza | PostgreSQL + PostGIS | podľa servera |
| Cache | Redis | podľa servera |
| Cloud | AWS (EC2, RDS, S3, CloudFront) | podľa servera |
| CI/CD | Xcode Cloud | zadarmo (25 h/mesiac) |
| Scraper | Apify Actor `janbuchar/multisport-map-scraper` | free tier |
| GPS obohacovanie | Apple Maps Server API | zadarmo (Apple Dev Program) |
| GPS fallback (dev only) | Google Places API (jednorazový import) | zadarmo ($200 kredit) |
| Verziovanie | Git + GitHub | zadarmo |
| Project mgmt | Jira / Linear | podľa plánu |

---

## 10. Harmonogram vývoja

### Fáza 1 – MVP (0–3 mesiace)

- Nastavenie projektu, CI/CD, architektúry
- Integrácia Apify Actor + enrich pipeline (Apple Maps Server API)
- Jednorazový Google Places fallback import
- Backend + PostgreSQL + PostGIS DB
- Mapa s pinmi, zoznam zariadení, základný filter
- Navigácia (MapKit, turn-by-turn)
- Detail zariadenia (GPS + hodiny z DB)
- Testovanie (Unit + UI testy)

### Fáza 2 – Beta (3–5 mesiacov)

- Autentifikácia (Sign in with Apple)
- Obľúbené zariadenia (sync na server)
- Offline mód (cached data)
- Push notifikácie
- Lokalizácia SK/CZ/EN
- TestFlight beta

### Fáza 3 – Production & Growth (5–7 mesiacov)

- App Store submission
- Skenovanie Multisport karty (kamera / NFC)
- Hodnotenia zariadení
- Rozšírenie na ďalšie krajiny (HU, PL)
- Apple Watch companion app (navigačné upozornenia)
- Rokovania s Benefit Systems o oficiálnom API

### Kapacita tímu (odhadovaná)

| Rola | Počet | Fázy |
| --- | --- | --- |
| iOS developer (Swift) | 2 | 1–3 |
| Backend developer | 1 | 1–3 |
| UI/UX dizajnér | 1 | 1–2 |
| QA engineer | 1 | 2–3 |
| Product Owner | 1 | 1–3 |

**Celkový odhad:** 7 mesiacov do App Store releasu\
**Odhadovaný rozpočet:** 70 000 – 110 000 € (bez nákladov na platené API — nulové prevádzkové náklady na dátovú vrstvu)

---

## 11. Produktový backlog – Initiative / Epic / User Story / Tasks

> Štruktúra je zostavená podľa metodiky **hierarchického product backlogu**: Initiative → Epic → User Story → Tasks. Aplikácia pokrýva presne tri funkcionality: zobrazenie športovísk na mape, filtrovanie a navádzanie do externej mapy.

---

### Initiative – Umožniť používateľovi nájsť a dostať sa na Multisport športovisko

**Cieľ:** Každý držiteľ Multisport karty nájde najbližšie vhodné športovisko a dostane sa tam do 3 ťuknutí.\
**Merateľný výsledok (KPI):** Počet spustených navigácií / mesiac na aktívneho používateľa.

---

#### Epic 1 – Objavovanie najbližšieho športoviska na mape

##### User Story 1.1

**Ako** držiteľ Multisport karty\
**chcem** vidieť všetky dostupné športoviská na mape v mojom okolí\
**aby som** vedel, kde sa nachádza najbližšie miesto, kde môžem cvičiť.

**Akceptačné kritériá:**

- Mapa sa zobrazí do 2 sekúnd od otvorenia aplikácie
- Piny sú farebne odlíšené podľa kategórie (fitness, bazén, tenis...)
- Po ťuknutí na pin sa zobrazí karta s názvom, vzdialenosťou a kategóriou
- Mapa je centrovaná na aktuálnu polohu používateľa

**Priorita:** 🔴 Must Have | **Story Points:** 8

**Tasks:**

| # | Task | Zodpovedný | Odhad |
| --- | --- | --- | --- |
| T-101 | Integrácia MapKit + CLLocationManager, žiadosť o povolenie lokácie | iOS dev | 3 h |
| T-102 | Custom MKAnnotation – ikona a farba podľa kategórie | iOS dev | 3 h |
| T-103 | API endpoint `GET /v1/venues/nearby` (lat, lon, radius) + PostGIS query | Backend dev | 5 h |
| T-104 | Bottom sheet po ťuknutí na pin (názov, vzdialenosť, kategória) | iOS dev | 3 h |

---

#### Epic 2 – Filtrovanie športovísk

##### User Story 2.1

**Ako** používateľ\
**chcem** filtrovať športoviská podľa typu aktivity\
**aby som** videl len miesta relevantné pre môj dnešný tréning.

**Akceptačné kritériá:**

- Filter sa otvorí po ťuknutí na tlačidlo filtra
- Možnosť vybrať jednu alebo viac kategórií súčasne
- Slider pre maximálnu vzdialenosť (0,5 – 20 km)
- Výsledky na mape sa okamžite aktualizujú po aplikovaní filtra

**Priorita:** 🔴 Must Have | **Story Points:** 5

**Tasks:**

| # | Task | Zodpovedný | Odhad |
| --- | --- | --- | --- |
| T-201 | Filter sheet UI – kategórie (checkboxy), slider vzdialenosti | iOS dev | 4 h |
| T-202 | FilterViewModel – stav filtra, aktualizácia mapy pri zmene | iOS dev | 3 h |
| T-203 | Rozšírenie API query o parametre `category` a `radius` | Backend dev | 2 h |

---

#### Epic 3 – Navigácia k vybranému športovisku

##### User Story 3.1

**Ako** používateľ\
**chcem** po výbere športoviska otvoriť navigáciu v externej mapovej aplikácii\
**aby som** sa tam dostal pomocou mapy, ktorú už poznám a používam.

**Akceptačné kritériá:**

- Tlačidlo „Navigovať" je dostupné na karte zariadenia
- Po ťuknutí sa zobrazí výber: Apple Maps, Google Maps, Waze (iba nainštalované)
- Vybraná aplikácia sa otvorí s predvyplneným cieľom (GPS súradnice zariadenia)
- Ak je dostupná iba jedna mapová aplikácia, otvorí sa priamo bez výberu

**Priorita:** 🔴 Must Have | **Story Points:** 3

**Tasks:**

| # | Task | Zodpovedný | Odhad |
| --- | --- | --- | --- |
| T-301 | Deep link pre Apple Maps (`maps://`), Google Maps (`comgooglemaps://`), Waze (`waze://`) | iOS dev | 3 h |
| T-302 | Detekcia nainštalovaných mapových aplikácií (`UIApplication.canOpenURL`) | iOS dev | 2 h |
| T-303 | Action sheet – výber aplikácie (zobrazí sa len ak je viac možností) | iOS dev | 2 h |

---

### Súhrnný prehľad backlogu

| Epic | User Story | Tasks | Story Points | Priorita |
| --- | --- | --- | --- | --- |
| 1 – Mapa a objavovanie | US 1.1 | T-101 až T-104 | 8 | 🔴 Must Have |
| 2 – Filtrovanie | US 2.1 | T-201 až T-203 | 5 | 🔴 Must Have |
| 3 – Navigácia (externá) | US 3.1 | T-301 až T-303 | 3 | 🔴 Must Have |
| **Spolu** | **3 user stories** | **10 taskov** | **16 SP** |  |