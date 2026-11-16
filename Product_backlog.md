# SportNav – Product Backlog


---

> Štruktúra: Initiative → Epic → User Story → Tasks.
> Aplikácia pokrýva presne tri funkcionality: zobrazenie športovísk na mape, filtrovanie a navádzanie do externej mapy.

---

## Initiative – Umožniť používateľovi nájsť a dostať sa na Multisport športovisko

**Cieľ:** Každý držiteľ Multisport karty nájde najbližšie vhodné športovisko a dostane sa tam do 3 ťuknutí.  
**KPI:** Počet spustených navigácií / mesiac na aktívneho používateľa.

---

### Epic 1 – Objavovanie najbližšieho športoviska na mape

#### User Story 1.1
**Ako** držiteľ Multisport karty  
**chcem** vidieť všetky dostupné športoviská na mape v mojom okolí  
**aby som** vedel, kde sa nachádza najbližšie miesto, kde môžem cvičiť.

**Akceptačné kritériá:**
- Mapa sa zobrazí do 2 sekúnd od otvorenia aplikácie
- Piny sú farebne odlíšené podľa kategórie (fitness, bazén, tenis...)
- Po ťuknutí na pin sa zobrazí karta s názvom, vzdialenosťou a kategóriou
- Mapa je centrovaná na aktuálnu polohu používateľa

**Priorita:** 🔴 Must Have | **Story Points:** 8

**Tasks:**

| # | Task | Zodpovedný | Odhad |
|---|---|---|---|
| T-101 | Integrácia MapLibre (dlaždice OpenFreeMap) + LocationManager, žiadosť o povolenie polohy | Android dev | 3 h |
| T-102 | Vrstva pinov (GeoJSON zdroj + clustering) – farba podľa kategórie | Android dev | 3 h |
| T-103 | SQLite query – načítanie venues v okruhu podľa GPS (Haversine formula) | Android dev | 5 h |
| T-104 | Bottom sheet (`ModalBottomSheet`) po ťuknutí na pin (názov, vzdialenosť, kategória, hodiny) | Android dev | 3 h |

---

### Epic 2 – Filtrovanie športovísk

#### User Story 2.1
**Ako** používateľ  
**chcem** filtrovať športoviská podľa typu aktivity  
**aby som** videl len miesta relevantné pre môj dnešný tréning.

**Akceptačné kritériá:**
- Filter sa otvorí po ťuknutí na tlačidlo filtra
- Možnosť vybrať jednu alebo viac kategórií súčasne
- Slider pre maximálnu vzdialenosť (0,5 – 20 km)
- Výsledky na mape sa okamžite aktualizujú po aplikovaní filtra

**Priorita:** 🔴 Must Have | **Story Points:** 5

**Tasks:**

| # | Task | Zodpovedný | Odhad |
|---|---|---|---|
| T-201 | Filter sheet UI (Jetpack Compose) – kategórie (checkboxy), slider vzdialenosti | Android dev | 4 h |
| T-202 | Stav filtra v MapViewModel (StateFlow), aktualizácia mapy pri zmene | Android dev | 3 h |
| T-203 | SQLite query rozšírená o filter kategórie a radius | Android dev | 2 h |

---

### Epic 3 – Navigácia k vybranému športovisku

#### User Story 3.1
**Ako** používateľ  
**chcem** po výbere športoviska otvoriť navigáciu v externej mapovej aplikácii  
**aby som** sa tam dostal pomocou mapy, ktorú už poznám a používam.

**Akceptačné kritériá:**
- Tlačidlo „Navigovať" je dostupné na karte zariadenia
- Po ťuknutí sa zobrazí výber: Google Maps, Waze, iná mapová aplikácia (iba nainštalované)
- Ak nie je nainštalovaná žiadna mapová aplikácia, zobrazí sa hláška (aplikácia nespadne)
- Vybraná aplikácia sa otvorí s predvyplneným cieľom (GPS súradnice zariadenia)
- Ak je dostupná iba jedna mapová aplikácia, otvorí sa priamo bez výberu

**Priorita:** 🔴 Must Have | **Story Points:** 3

**Tasks:**

| # | Task | Zodpovedný | Odhad |
|---|---|---|---|
| T-301 | Intenty pre Google Maps (`google.navigation:`), Waze (`https://waze.com/ul`) a inú mapovú aplikáciu (`geo:`) | Android dev | 3 h |
| T-302 | Detekcia nainštalovaných mapových aplikácií (`PackageManager` + `<queries>` v manifeste) | Android dev | 2 h |
| T-303 | Dialóg výberu aplikácie (zobrazí sa len ak je viac možností) | Android dev | 2 h |

---

## Súhrnný prehľad

| Epic | User Story | Tasks | Story Points | Priorita |
|---|---|---|---|---|
| 1 – Mapa a objavovanie | US 1.1 | T-101 až T-104 | 8 | 🔴 Must Have |
| 2 – Filtrovanie | US 2.1 | T-201 až T-203 | 5 | 🔴 Must Have |
| 3 – Navigácia (externá) | US 3.1 | T-301 až T-303 | 3 | 🔴 Must Have |
| **Spolu** | **3 user stories** | **10 taskov** | **16 SP** | |
